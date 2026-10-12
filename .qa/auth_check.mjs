const targets = await (await fetch('http://127.0.0.1:9223/json')).json();
const socket = new WebSocket(targets.find(item => item.type === 'page').webSocketDebuggerUrl);
await new Promise(resolve => socket.addEventListener('open',resolve,{once:true}));
let nextId = 0;
const pending = new Map();
socket.addEventListener('message', event => {
  const value = JSON.parse(event.data);
  if (!value.id || !pending.has(value.id)) return;
  const {resolve,reject} = pending.get(value.id); pending.delete(value.id);
  value.error ? reject(new Error(JSON.stringify(value.error))) : resolve(value.result);
});
function send(method,params={}) {
  return new Promise((resolve,reject) => { const id=++nextId; pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params})); });
}
async function evaluate(expression) {
  const result = await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);
  return result.result.value;
}
const pause=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
function check(value,message){if(!value)throw new Error(message);}
try {
  await send('Page.enable'); await send('Network.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:'http://127.0.0.1:5051'}); await pause(1500);
  check(await evaluate('document.getElementById("login-dialog").open'),'Login dialog missing');
  await evaluate('document.getElementById("login-token").value="wrong-test-token";document.getElementById("login-form").requestSubmit()'); await pause(500);
  check(await evaluate('!document.getElementById("login-error").hidden && document.getElementById("login-dialog").open'),'Wrong token not rejected');
  await evaluate('document.getElementById("login-token").value="noc-qa-view-token";document.getElementById("login-form").requestSubmit()'); await pause(3000);
  check(await evaluate('!document.getElementById("login-dialog").open && document.getElementById("hostname").textContent.length>0'),'Valid login failed');
  const cookies=await send('Network.getCookies',{urls:['http://127.0.0.1:5051']});
  check(cookies.cookies.some(cookie=>cookie.name==='noc_session'&&cookie.httpOnly&&cookie.sameSite==='Strict'),'Cookie protection missing');
  check(await evaluate('Array.from(document.querySelectorAll(".restart-button")).every(button=>button.disabled)'),'Unavailable restarts enabled');
  const report={hostname:'qa-edge',cpu_percent:98,memory:{used:10,total:100,percent:10},disk:{used:20,total:100,percent:20},services:[{name:'nginx',status:'failed'}]};
  const response=await fetch('http://127.0.0.1:5051/api/vps/report',{method:'POST',headers:{'Content-Type':'application/json','x-vps-token':'noc-qa-vps-token'},body:JSON.stringify(report)});
  check(response.ok,'VPS report rejected'); await pause(2500);
  check(await evaluate('document.getElementById("vps-list").innerText.includes("qa-edge")'),'VPS not shown');
  await evaluate('document.getElementById("autoscroll-button").click()');
  check(await evaluate('document.getElementById("autoscroll-button").getAttribute("aria-pressed")==="false"'),'Console pause failed');
  await evaluate('document.getElementById("logout-button").click()'); await pause(1500);
  check(await evaluate('document.getElementById("login-dialog").open'),'Logout did not lock dashboard');
  check(await evaluate('!document.body.innerText.includes("qa-edge")'),'Logout retained protected data');
  console.log('PASS: login, wrong token, signed HttpOnly cookie, disabled restart, live VPS report, console pause, logout and protected data cleanup');
} finally {socket.close();}
