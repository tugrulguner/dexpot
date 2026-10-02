export const MAX_ITEMS = 20;
export function createState() { return { items: new Map([[1, { id: 1, name: 'starter', price: 9.99 }]]), nextId: 2, result: null }; }
export function execute(state, request) {
  const { operation: op, id, name, price } = request;
  const methods = { create: 'POST', update: 'PUT', get: 'GET', delete: 'DELETE' };
  if (!methods[op]) throw new Error('unknown operation');
  const path = op === 'create' ? '/items' : `/items/${id}`;
  const payload = { method: methods[op], path, ...(['create', 'update'].includes(op) ? { body: { name, price } } : {}) };
  let status, body;
  if (op !== 'create' && !Number.isInteger(id)) { status = 422; body = { detail: 'invalid int for item_id' }; }
  else if (['create', 'update'].includes(op) && (typeof name !== 'string' || !Number.isFinite(price))) { status = 422; body = { detail: 'request body must contain a string name and finite price' }; }
  else if (op === 'create') {
    if (state.items.size >= MAX_ITEMS) { status = 422; body = { detail: 'browser state is limited to 20 items' }; }
    else { const item = { id: state.nextId++, name, price }; state.items.set(item.id, item); status = 201; body = item; }
  } else if (op === 'get') { body = state.items.get(id); status = body ? 200 : 404; if (!body) body = { detail: 'item not found' }; }
  else if (op === 'update') { if (!state.items.has(id)) { status = 404; body = { detail: 'item not found' }; } else { body = { id, name, price }; state.items.set(id, body); status = 200; } }
  else { if (!state.items.has(id)) { status = 404; body = { detail: 'item not found' }; } else { state.items.delete(id); status = 200; body = { deleted: id }; } }
  return { state: { ...state, result: { request: payload, response: { status, body } } }, result: { request: payload, response: { status, body } } };
}
