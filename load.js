import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://host.docker.internal:8000';
const MODE = __ENV.MODE || 'spread'; // 'spread' | 'hot' | 'health'
// 'health' hits GET /health: same FastAPI + middleware + logging cost, no DB work.
// Its rate is the ceiling any cache in front of the DB could reach.
const REQ_TAG = MODE === 'health' ? 'health' : 'redirect';
const VUS = Number(__ENV.VUS || 50);
const DURATION = __ENV.DURATION || '30s';

export const options = {
  setupTimeout: '300s',

  scenarios: {
    redirects: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
    },
  },

  thresholds: {
    [`http_req_duration{name:${REQ_TAG}}`]: ['p(95)<500'],
    [`http_req_failed{name:${REQ_TAG}}`]: ['rate<0.01'],
  },
};

export function setup() {
  if (MODE === 'health') return { codes: [] };
  const headers = { 'Content-Type': 'application/json' };
  const codes = [];
  for (let i = 0; i < 1000; i++) {
    const res = http.post(
      `${BASE}/urls`,
      JSON.stringify({ url: `https://example.com/page/${i}` }),
      { headers,  tags: { name: 'create' } }
    );
    codes.push(res.json('code'));
  }
  return { codes };
}

export default function (data) {
  if (MODE === 'health') {
    const r = http.get(`${BASE}/health`, { tags: { name: 'health' } });
    check(r, { 'is 200': (res) => res.status === 200 });
    return;
  }

  // TODO 1: pick `code`.
  //   spread -> a random code from data.codes
  //   hot    -> always the same code, 
  const code =MODE === 'hot'
  ? data.codes[0]
  : data.codes[Math.floor(Math.random() * data.codes.length)];

  const res = http.get(`${BASE}/${code}`, { redirects: 0 , tags: { name: 'redirect' } }); // do NOT follow the 302
  check(res, { 'is 302': (r) => r.status === 302 });
}

// TODO 2: after your first run, add a `thresholds` entry to `options`
// that fails the run if p95 exceeds a number you choose, and explain your choice.
