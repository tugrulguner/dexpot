local threads = {}
function setup(thread) table.insert(threads, thread) end
function init(args) good,bad,n=0,0,0; mode=args[1] or 'item' end
local mixed_paths = {"/items/7","/items/7","/io","/cpu"}
function request()
  n=n+1
  local path="/items/7"
  if mode=='mixed' then path=mixed_paths[((n-1)%#mixed_paths)+1]
  elseif mode=='nested' then path="/nested/7"
  elseif mode=='large_nested' then path="/large-nested" end
  return wrk.format('GET',path)
end
local expected = {
  item={status=200,body="{\"id\":7,\"name\":\"item-7\",\"price\":9.99}"},
  nested={status=200,body="{\"id\":7,\"name\":\"item-7\",\"details\":{\"category\":\"demo\",\"dimensions\":{\"width\":2,\"height\":3}}}"}
}
local large_rows={}
for i=1,64 do
  large_rows[i]=string.format('{"id":%d,"name":"item-%d","details":{"category":"demo","dimensions":{"width":2,"height":3}}}',i,i)
end
local expected_large='['..table.concat(large_rows,',')..']'
function response(status,headers,body)
  local spec=expected[mode] or expected.item
  local valid=status==spec.status and body==spec.body
  if mode=='large_nested' then valid=status==200 and body==expected_large end
  if valid then good=good+1 else bad=bad+1 end
end
function done(summary,latency,requests)
  print(string.format('HISTOGRAM {"samples":%d}',#latency))
  local g,b=0,0
  for _,t in ipairs(threads) do g=g+t:get('good'); b=b+t:get('bad') end
  print(string.format('METRICS {"good":%d,"bad":%d,"requests":%d,"duration_us":%d,"p50_us":%f,"p95_us":%f,"p99_us":%f,"connect_errors":%d,"read_errors":%d,"write_errors":%d,"timeout_errors":%d}',g,b,summary.requests,summary.duration,latency:percentile(50),latency:percentile(95),latency:percentile(99),summary.errors.connect,summary.errors.read,summary.errors.write,summary.errors.timeout))
end
