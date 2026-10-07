// Optional load: `make load`. TLS correctness is asserted by the prober and
// assertions.sh (strict, root-only trust); k6 measures latency under load.
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  insecureSkipTLSVerify: true,
  scenarios: {
    steady: { executor: 'constant-arrival-rate', rate: 50, timeUnit: '1s', duration: '60s', preAllocatedVUs: 20 },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],          // availability SLO 99%
    http_req_duration: ['p(95)<200', 'p(99)<500'],
    checks: ['rate>0.99'],
  },
};

export default function () {
  const r = http.get(__ENV.TARGET);
  check(r, {
    'status 200': (x) => x.status === 200,
    'flag header from backend': (x) => !!x.headers['X-Vantage-Flag'],
  });
}
