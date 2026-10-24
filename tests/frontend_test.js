/* SPDX-License-Identifier: GPL-2.0-only */
/* Execute the real page script with a small DOM/API model; never contact a device. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const nodes = [], ids = new Map();
class Element {
 constructor(tag='div') { this.tag=tag;this.dataset={};this.children=[];this.files=[];this.value='';this.textContent='';this.classList={toggle(){}};nodes.push(this); }
 append(...items) { for(const item of items){item.parent=this;this.children.push(item);} }
 appendChild(item) { this.append(item); }
 replaceChildren() { this.children=[]; }
 replaceWith(item) { if(this.parent){const index=this.parent.children.indexOf(this);this.parent.children[index]=item;item.parent=this.parent;} }
 get options() { return this.children; }
}
const document = {
 documentElement:{},
 getElementById(id){if(!ids.has(id))ids.set(id,new Element());return ids.get(id);},
 createElement(tag){return new Element(tag);},
 querySelector(selector){return this.getElementById(selector);},
 querySelectorAll(selector){
  if(selector==='[data-t]')return nodes.filter(n=>n.dataset.t);
  if(selector==='button,input,select')return nodes.filter(n=>['button','input','select'].includes(n.tag));
  return [];
 }
};
const device={model:'TYFZA1',ram_bytes:536870912,flash_bytes:268435456,version:'U-Boot TYFZA1 1.1',
 project_version:'1.1',build_commit:'abcdef0-dirty',ports:'4×GE',ubi:true,board_data:[]};
const context=vm.createContext({document,navigator:{language:'en'},location:{hostname:'127.0.0.1',port:'8924'},
 assert,device,console,setTimeout(){},clearTimeout(){},fetch:async url=>{
 assert(['/api/device','/api/storage','/api/task'].includes(url));
 return {ok:true,json:async()=>url==='/api/device'?device:url==='/api/storage'?{targets:[]}:{busy:false}};
}});
let script=fs.readFileSync(path.join(__dirname,'../overlay/net/lwip/httpd-page.html'),'utf8').split('<script>')[1].split('</script>')[0];
// Avoid background refresh/monitoring; all foreground handlers stay unchanged.
script=script.slice(0,script.indexOf("document.querySelectorAll('input[type=file]').forEach(filePicker);"));
vm.runInContext(script,context);
(async()=>{
 await vm.runInContext('refresh()',context);
 assert.equal(document.getElementById('version').textContent,'1.1');
 assert.equal(document.getElementById('commit').textContent,'abcdef0-dirty');
 device.ports='';await vm.runInContext('refresh()',context);
 assert.equal(document.getElementById('ports').textContent,'Unknown');
 vm.runInContext("language='zh';applyLanguage()",context);
 assert.equal(document.getElementById('ports').textContent,'未识别');
 device.ports='2.5GE + 3×GE';device.build_commit='';await vm.runInContext('refresh()',context);
 assert.equal(document.getElementById('ports').textContent,'2.5GE + 3×GE');
 assert.equal(document.getElementById('commit').textContent,'');
 vm.runInContext(`
 targets=[{kind:'mtd',name:'nand0',whole:true,size:268435456},
          {kind:'mtd',name:'boot',whole:false,size:2097152},
          {kind:'mtd',name:'env',whole:false,size:262144},
          {kind:'ubi',name:'ubi_Config',size:6356992}];
 catalog();
 assert.equal(el('backupTarget').options.length,4);
 assert.equal(el('writeTarget').options.length,2);
 assert.equal(el('writeTarget').options.map(o=>targets[Number(o.value)].name).join(','),'env,ubi_Config');
 const pickerInput=document.createElement('input'),picker=filePicker(pickerInput);
 assert.equal(picker.children[1].textContent,'选择文件');
 assert.equal(picker.children[2].textContent,'未选择文件');
 pickerInput.files=[{name:'<test>.bin'}];pickerInput.onchange();
 language='en';applyLanguage();
 assert.equal(picker.children[1].textContent,'Choose file');
 assert.equal(picker.children[2].textContent,'<test>.bin');
 pickerInput.files=[];pickerInput.onchange();assert.equal(picker.children[2].textContent,'No file selected');
 `,context);
 const restore=JSON.parse(await vm.runInContext(fs.readFileSync(path.join(__dirname,'browser_restore_fixture.js'),'utf8'),context));
 assert.equal(restore.results.length,5);
 console.log('Version/commit, both boards, translation, file selection and five restore flows passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
