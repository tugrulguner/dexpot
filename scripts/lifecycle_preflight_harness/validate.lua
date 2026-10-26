-- Every native client thread has a fixed route, even in the mixed cohort.
-- This permits exact per-response route/body validation with concurrent sockets.
local threads = {}
local routes = {"flat", "nested", "cpu", "io"}
local flat = '{"id":7,"name":"item-7","price":9.99}'
local children = {}
for i = 0,15 do
  children[#children+1] = string.format('{"id":%d,"name":"item-%d","price":9.99}', i, i)
end
local nested = '{"items":[' .. table.concat(children, ',') .. '],"title":"group"}'

function setup(thread)
  threads[#threads+1] = thread
  thread:set("slot", #threads)
end

function init(args)
  local profile = args[1]
  assert(profile == 'flat' or profile == 'nested' or profile == 'mixed', 'unknown profile')
  route = profile == 'mixed' and routes[(slot-1)%4+1] or profile
  expected_body = route == 'nested' and nested or flat
  wrk.path = '/' .. route
  good, bad = 0, 0
end

function response(status, headers, body)
  if status == 200 and body == expected_body then good = good + 1
  else bad = bad + 1 end
end

function done(summary, latency, requests)
  local good, bad = 0, 0
  local counts = {flat=0,nested=0,cpu=0,io=0}
  for _, thread in ipairs(threads) do
    good = good + thread:get('good')
    bad = bad + thread:get('bad')
    local route = thread:get('route')
    counts[route] = counts[route] + thread:get('good')
  end
  print(string.format('METRICS {"requests":%d,"good":%d,"bad":%d,"duration_us":%d,"p50_us":%d,"p95_us":%d,"p99_us":%d,"connect_errors":%d,"read_errors":%d,"write_errors":%d,"timeout_errors":%d,"flat_good":%d,"nested_good":%d,"cpu_good":%d,"io_good":%d}',
    summary.requests,good,bad,summary.duration,latency:percentile(50),latency:percentile(95),latency:percentile(99),summary.errors.connect,summary.errors.read,summary.errors.write,summary.errors.timeout,counts.flat,counts.nested,counts.cpu,counts.io))
end
