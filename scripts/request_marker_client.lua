-- Append to byte-identical original validate.lua in the SAME chunk.
-- Callback boundaries are not kernel socket send/read timestamps.
local ffi = require('ffi')
ffi.cdef[[struct dexpot_marker_timeval { long tv_sec; int tv_usec; }; int gettimeofday(void *, void *); int getpid(void);]]
local tv = ffi.new('struct dexpot_marker_timeval')
assert(ffi.sizeof(tv) == 16, 'unsupported timeval ABI')
local function wall_us()
  if ffi.C.gettimeofday(tv, nil) ~= 0 then return nil end
  return tonumber(tv.tv_sec)*1000000 + tonumber(tv.tv_usec)
end
local old_init, old_response, old_done = init, response, done
local enabled = os.getenv('DIAG_ENABLED') == '1'
local directory = os.getenv('DIAG_DIR')
local pid = tonumber(ffi.C.getpid())
local sequence, count, ready = 0, 0, false
local base, output = nil, nil
local pending = {}
diag_prepared, diag_received, diag_pending = 0, 0, 0
diag_dropped, diag_clock_errors, diag_unmatched = 0, 0, 0
local function record(id, event, timestamp)
  if not timestamp then diag_clock_errors = diag_clock_errors + 1 end
  if count >= 4096 or not output then diag_dropped = diag_dropped + 1; return end
  local line = string.format('{"id":"%s","event":"%s","wall_us":%s}\n', id, event, timestamp and string.format('%.0f',timestamp) or 'null')
  local ok = output:write(line)
  if ok then ok = output:flush() end
  if not ok then diag_dropped = diag_dropped + 1 end
  count = count + 1
end
function init(args)
  old_init(args)
  base = wrk.format()
  ready = true
  if enabled then
    output = io.open(string.format('%s/client-%d-%d.jsonl', directory, pid, slot), 'w')
  end
end
function request()
  if not ready then return wrk.format() end
  sequence = sequence + 1
  if not enabled or sequence % 64 ~= 0 then return base end
  local id = string.format('%d-%d-%d', pid, slot, sequence)
  local timestamp = wall_us()
  pending[id] = {timestamp}
  diag_prepared, diag_pending = diag_prepared + 1, diag_pending + 1

  local marked, replacements = base:gsub('\r\n\r\n', '\r\nX-Dexpot-Diag-Id: '..id..'\r\n\r\n', 1)
  assert(replacements == 1, 'original request framing not found')
  return marked
end
function response(status, headers, body)
  local timestamp = wall_us()
  local id = headers['X-Dexpot-Diag-Id'] or headers['x-dexpot-diag-id']
  if enabled and id then
    if pending[id] then
      local prepared = pending[id][1]
      pending[id] = nil
      diag_pending, diag_received = diag_pending - 1, diag_received + 1
      record(id, 'Crequest_prepared', prepared)
      record(id, 'Cresponse_callback_entry', timestamp)
    else
      diag_unmatched = diag_unmatched + 1
    end
  end
  old_response(status, headers, body)
end
function done(summary, latency, requests)
  old_done(summary, latency, requests)
  for _, thread in ipairs(threads) do
    print(string.format('DIAG_SUMMARY {"slot":%d,"prepared":%d,"received":%d,"pending":%d,"dropped":%d,"clock_errors":%d,"unmatched":%d}', thread:get('slot'), thread:get('diag_prepared'), thread:get('diag_received'), thread:get('diag_pending'), thread:get('diag_dropped'), thread:get('diag_clock_errors'), thread:get('diag_unmatched')))
  end
end
