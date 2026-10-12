import fs from 'node:fs/promises';

const targets = await (await fetch('http://127.0.0.1:9223/json')).json();
const target = targets.find(item => item.type === 'page');
if (!target) throw new Error('Chrome page missing');
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, {once:true}); socket.addEventListener('error', reject, {once:true}); });
let nextId = 0;
const pending = new Map();
const errors = [];
socket.addEventListener('message', event => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const callbacks = pending.get(message.id);
    pending.delete(message.id);
    message.error ? callbacks.reject(new Error(JSON.stringify(message.error))) : callbacks.resolve(message.result);
  }
  if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
  if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') errors.push(message.params.args.map(arg => arg.value || arg.description).join(' '));
});
function send(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    pending.set(id, {resolve,reject});
    socket.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const value = await send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true});
  if (value.exceptionDetails) throw new Error(value.exceptionDetails.text);
  return value.result.value;
}
try {
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride', {width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate', {url:'http://127.0.0.1:5050'});
  await new Promise(resolve => setTimeout(resolve, 4500));
  const desktop = await evaluate(`({title:document.title, width:innerWidth, scroll:document.documentElement.scrollWidth, text:document.body.innerText.slice(0,1800), buttons:document.querySelectorAll('button').length})`);
  if (desktop.scroll > desktop.width) throw new Error('Desktop horizontal overflow');
  await fs.mkdir('docs', {recursive:true});
  const screenshot = await send('Page.captureScreenshot', {format:'png', captureBeyondViewport:false});
  await fs.writeFile('docs/preview.png', Buffer.from(screenshot.data, 'base64'));
  await send('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:true});
  await new Promise(resolve => setTimeout(resolve,500));
  const mobile = await evaluate(`({width:innerWidth,scroll:document.documentElement.scrollWidth,text:document.body.innerText.slice(0,200)})`);
  const mobileScreenshot = await send('Page.captureScreenshot', {format:'png', captureBeyondViewport:false});
  await fs.writeFile('docs/preview-mobile.png', Buffer.from(mobileScreenshot.data,'base64'));
  if (mobile.scroll > mobile.width) throw new Error('Mobile horizontal overflow');
  if (errors.length) throw new Error('Browser JavaScript errors: ' + errors.join('; '));
  console.log(JSON.stringify({desktop,mobile,javascriptErrors:errors},null,2));
} finally {
  socket.close();
}
