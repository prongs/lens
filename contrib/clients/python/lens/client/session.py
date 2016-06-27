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

import csv
import time
import zipfile

import requests
from six import string_types, BytesIO, PY2, PY3

from .models import WrappedJson
from .utils import conf_to_xml


class LensSessionClient(object):
    def __init__(self, base_url, username, password, database, conf):
        self.base_url = base_url + "session/"
        self.open(username, password, database, conf)

    def __getitem__(self, key):
        resp = requests.get(self.base_url + "params",
                            params={'sessionid': self._sessionid, 'key': key},
                            headers={'accept': 'application/json'})
        if resp.ok:
            params = resp.json(object_hook=WrappedJson)
            text = params.elements[0]
            if key in text:
                text = text[len(key)+1:]
            return text

    def open(self, username, password, database, conf):
        payload = [('username', username), ('password', password), ('sessionconf', conf_to_xml(conf))]
        if database:
            payload.append(('database', database))
        r = requests.post(self.base_url, files=payload, headers={'accept': 'application/xml'})
        r.raise_for_status()
        self._sessionid = r.text

    def close(self):
        requests.delete(self.base_url, params={'sessionid': self._sessionid})

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
