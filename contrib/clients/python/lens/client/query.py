#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import time
import zipfile

import requests
from six import string_types, BytesIO, PY2, PY3
from .models import WrappedJson
from .utils import conf_to_xml
import csv
if PY3:
    from collections.abc import Iterable as Iterable
elif PY2:
    from collections import Iterable as Iterable


class LensQuery(WrappedJson):
    def __init__(self, client, *args, **kwargs):
        super(LensQuery, self).__init__(*args, **kwargs)
        self.client = client

    @property
    def finished(self):
        return self.status.status in ('SUCCESSFUL', 'FAILED', 'CANCELED', 'CLOSED')

    def get_result(self, *args, **kwargs):
        return self.client.get_result(self, *args, **kwargs)

    result = property(get_result)


type_mappings = {'BOOLEAN': bool,
                 'TINYINT': int,
                 'SMALLINT': int,
                 'INT': int,
                 'BIGINT': long,
                 'FLOAT': float,
                 'DOUBLE': float,
                 'TIMESTAMP': long,
                 'BINARY': bin,
                 'ARRAY': list,
                 'MAP': dict,
                 # 'STRUCT,': str,
                 # 'UNIONTYPE,': float,
                 # 3'USER_DEFINED,': float,
                 'DECIMAL,': float,
                 # 'NULL,': float,
                 # 'DATE,': float,
                 # 'VARCHAR,': float,
                 # 'CHAR': float
                 }
default_mapping = lambda x: x


class LensQueryResult(Iterable):
    def __init__(self, header, response, encoding=None, is_header_present=True, delimiter=",",
                 custom_mappings=None):
        if custom_mappings is None:
            custom_mappings = {}
        self.custom_mappings = custom_mappings
        self.response = response
        self.is_zipped = 'zip' in self.response.headers['content-disposition']
        self.delimiter = str(delimiter)
        self.is_header_present = is_header_present
        self.encoding = encoding
        self.header = header

    def _mapping(self, index):
        type_name = self.header.columns[index].type
        if type_name in self.custom_mappings:
            return self.custom_mappings[type_name]
        if type_name in type_mappings:
            return type_mappings[type_name]
        return default_mapping

    def _parse_line(self, line):
        return list(self._mapping(index)(line[index]) for index in range(len(line)))

    def __iter__(self):
        byte_stream = BytesIO(self.response.content)
        if self.is_zipped:
            with zipfile.ZipFile(byte_stream) as self.zipfile:
                for name in self.zipfile.namelist():
                    with self.zipfile.open(name) as single_file:
                        if name[-3:] == 'csv':
                            reader = csv.reader(single_file, delimiter=self.delimiter)
                        else:
                            reader = single_file
                        reader_iterator = iter(reader)
                        if self.is_header_present:
                            next(reader_iterator)
                        for line in reader_iterator:
                            yield self._parse_line(line)
        else:
            reader = csv.reader(byte_stream, delimiter=self.delimiter)
            reader_iterator = iter(reader)
            if self.is_header_present:
                next(reader_iterator)
            for line in reader_iterator:
                yield self._parse_line(line)
        byte_stream.close()


class LensQueryClient(object):
    def __init__(self, base_url, session):
        self._session = session
        self.base_url = base_url + "queryapi/"
        self.launched_queries = []
        self.finished_queries = {}
        self.query_confs = {}
        self.is_header_present_in_result = bool(self._session['lens.query.output.write.header'])

    def __call__(self, **filters):
        filters['sessionid'] = self._session._sessionid
        resp = requests.get(self.base_url + "queries/", params=filters, headers={'accept': 'application/json'})
        return self.sanitize_response(resp)

    def __getitem__(self, item):
        if isinstance(item, string_types):
            if item in self.finished_queries:
                return self.finished_queries[item]
            resp = requests.get(self.base_url + "queries/" + item, params={'sessionid': self._session._sessionid},
                                headers={'accept': 'application/json'})
            resp.raise_for_status()
            query = LensQuery(self, resp.json(object_hook=WrappedJson))
            if query.finished:
                query.client = self
                self.finished_queries[item] = query
            return query
        elif isinstance(item, LensQuery):
            return self[item.query_handle]
        elif isinstance(item, WrappedJson):
            if item._is_wrapper:
                return self[item._wrapped_value]
        raise Exception("Can't get query: " + str(item))

    def submit(self, query, operation=None, query_name=None, timeout=None, conf=None, wait=False, fetch_result=False,
               *args, **kwargs):
        payload = [('sessionid', self._session._sessionid), ('query', query)]
        if query_name:
            payload.append(('queryName', query_name))
        if timeout:
            payload.append(('timeoutmillis', timeout))
        if not operation:
            operation = "execute_with_timeout" if timeout else "execute"
        payload.append(('operation', operation))
        payload.append(('conf', conf_to_xml(conf)))
        resp = requests.post(self.base_url + "queries/", files=payload, headers={'accept': 'application/json'})
        query = self.sanitize_response(resp)
        if conf:
            self.query_confs[str(query)] = conf
        if wait or fetch_result:
            self.wait_till_finish(query)
        if fetch_result:
            # get result and return
            return self.get_result(query, *args, **kwargs)  # query is handle here
        elif wait:
            # fetch details and return
            return self.wait_till_finish(query, *args, **kwargs)
        # just return handle. This would be the async case. Or execute with timeout, without wait
        return query

    def wait_till_finish(self, handle_or_query, poll_interval=5):
        while not self[handle_or_query].finished:
            time.sleep(poll_interval)
        return self[handle_or_query]

    def get_result(self, handle_or_query, *args, **kwargs):
        query = self.wait_till_finish(handle_or_query)
        handle = str(query.query_handle)
        if query.status.status == 'SUCCESSFUL' and query.status.is_result_set_available:
            resp = requests.get(self.base_url + "queries/" + handle + "/resultsetmetadata",
                                params={'sessionid': self._session._sessionid}, headers={'accept': 'application/json'})
            metadata = self.sanitize_response(resp)
            # Try getting the result through http result
            resp = requests.get(self.base_url + "queries/" + handle + "/httpresultset",
                                params={'sessionid': self._session._sessionid}, stream=True)
            if resp.ok:
                is_header_present = self.is_header_present_in_result
                if not is_header_present:
                    if handle in self.query_confs and 'lens.query.output.write.header' in self.query_confs[handle]:
                        is_header_present = bool(self.query_confs[handle]['lens.query.output.write.header'])
                return LensQueryResult(metadata, resp, is_header_present=is_header_present, *args, **kwargs)
            else:
                resp = requests.get(self.base_url + "queries/" + handle + "/resultset",
                                    params={'sessionid': self._session._sessionid}, headers={'accept': 'application/json'})
                return self.sanitize_response(resp)

        else:
            raise Exception("Result set not available")

    def sanitize_response(self, resp):
        resp.raise_for_status()
        try:
            resp_json = resp.json(object_hook=WrappedJson)
            if 'lensAPIResult' in resp_json:
                resp_json = resp_json.lens_a_p_i_result
                if 'error' in resp_json:
                    raise Exception(resp_json['error'])
                if 'data' in resp_json:
                    data = resp_json.data
                    if len(data) == 2 and 'type' in data:
                        keys = list(data.keys())
                        keys.remove('type')
                        return WrappedJson({data['type']: data[keys[0]]})
                    return data
        except:
            resp_json = resp.json()
        return resp_json
