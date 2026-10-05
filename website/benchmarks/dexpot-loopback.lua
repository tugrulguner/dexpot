local threads = {}

function setup(worker)
  worker:set("responses", 0)
  worker:set("invalid", 0)
  table.insert(threads, worker)
end

function request()
  return wrk.format("GET", "/items/7")
end

function response(status, headers, body)
  wrk.thread:set("responses", wrk.thread:get("responses") + 1)
  if status ~= 200 or body ~= '{"id":7,"name":"item-7","price":7.0}' then
    wrk.thread:set("invalid", wrk.thread:get("invalid") + 1)
  end
end

function done(summary, latency, requests_summary)
  local total_responses = 0
  local total_invalid = 0
  for _, worker in ipairs(threads) do
    total_responses = total_responses + worker:get("responses")
    total_invalid = total_invalid + worker:get("invalid")
  end
  io.write(string.format("validated_responses=%d invalid_responses=%d\n", total_responses, total_invalid))
end
