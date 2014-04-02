package com.inmobi.grill.server;

import javax.ws.rs.ClientErrorException;
import javax.ws.rs.ServerErrorException;

import org.glassfish.jersey.server.monitoring.RequestEvent;
import org.glassfish.jersey.server.monitoring.RequestEventListener;

import com.inmobi.grill.server.api.metrics.MetricsService;

/**
 * Event listener used for metrics in errors
 *
 */
public class GrillRequestListener implements RequestEventListener {
  public static final String HTTP_REQUESTS_STARTED = "http-requests-started";
  public static final String HTTP_REQUESTS_FINISHED = "http-requests-finished";
  public static final String HTTP_ERROR = "http-error";
  public static final String HTTP_SERVER_ERROR = "http-server-error";
  public static final String HTTP_CLIENT_ERROR = "http-client-error";
  public static final String HTTP_UNKOWN_ERROR = "http-unkown-error";
  public static final String EXCEPTION_COUNT = "count";
  
  
  @Override
  public void onEvent(RequestEvent event) {
    if (RequestEvent.Type.ON_EXCEPTION == event.getType()) {
      Throwable error = event.getException();
      if (error != null) {
        Class<?> errorClass = error.getClass();
        MetricsService metrics = 
            (MetricsService) GrillServices.get().getService(MetricsService.NAME);
        if (metrics != null) {
          // overall error counter
          metrics.incrCounter(GrillRequestListener.class, HTTP_ERROR);
          // detailed per excepetion counter
          metrics.incrCounter(errorClass, EXCEPTION_COUNT);
          
          if (error instanceof ServerErrorException) {
            // All 5xx errors (ex - internal server error)
            metrics.incrCounter(GrillRequestListener.class, HTTP_SERVER_ERROR); 
          } else if (error instanceof ClientErrorException) {
            // Error due to invalid request - bad request, 404, 403
            metrics.incrCounter(GrillRequestListener.class, HTTP_CLIENT_ERROR);
          } else {
            metrics.incrCounter(GrillRequestListener.class, HTTP_UNKOWN_ERROR);
            error.printStackTrace();
          }
        }
      }
    } else if (RequestEvent.Type.FINISHED == event.getType()) {
      MetricsService metrics = (MetricsService) GrillServices.get().getService(MetricsService.NAME);
      if (metrics != null) {
        metrics.incrCounter(GrillRequestListener.class, HTTP_REQUESTS_FINISHED);
      }
    }

  }
}
