/* SPDX-License-Identifier: GPL-2.0-only */
/* Evaluate only on tests/preview.py's localhost page; all write APIs are replaced. */
(async () => {
 if(location.hostname!=='127.0.0.1'||location.port!=='8924')throw new Error('Wrong fixture page');
 const savedTask=task,savedTransfer=transfer,input=el('allFlashImage'),savedFiles=Object.getOwnPropertyDescriptor(input,'files');
 const results=[];
 const check=(condition,message)=>{if(!condition)throw new Error(message)};
 try{
  const total=256*1024*1024;
  flashBytes=total;
  for(const mode of ['success','upload-fail','write-fail','cancel','wrong-size']){
   const calls=[],uploads=[];
   let next=2*1024*1024;
   Object.defineProperty(input,'files',{configurable:true,value:[{
    size:mode==='wrong-size'?total-1:total,
    slice:(begin,end)=>({begin,end:Math.min(end,total),size:Math.min(end,total)-begin})
   }]});
   task=async payload=>{
    calls.push({...payload});
    if(payload.operation==='restore-start')return {restore_id:9617,restore_offset:next};
    check(payload.restore_id===9617,'Restore session id lost');
    if(payload.operation==='restore-chunk'){
     check(payload.offset===next,'Out-of-order chunk');
     if(mode==='write-fail'&&payload.offset>6*1024*1024)throw new Error('injected MTD readback failure');
     next+=Math.min(4*1024*1024,total-next);
     if(mode==='cancel')cancelRestore=true;
    }
    return {};
   };
   transfer=async (url,body,type,base,full)=>{
    check(url==='/api/upload','Whole-chip RAM upload endpoint was used');
    check(body.size<=4*1024*1024,'Upload exceeds the 4 MiB bound');
    check(base===body.begin&&full===total,'Progress does not represent the whole backup');
    uploads.push({begin:body.begin,end:body.end,size:body.size});
    if(mode==='upload-fail'&&uploads.length===3)throw new Error('injected upload failure');
    return {upload_id:uploads.length};
   };
   remoteBusy=false;localBusy=false;serverRestore=0;activeRestore=0;
   await el('allFlashButton').onclick();
   const operations=calls.map(c=>c.operation);
   if(mode==='success'){
    check(operations[0]==='restore-start'&&operations.at(-1)==='restore-finish','Restore start/finish order wrong');
    check(!operations.includes('restore-cancel'),'Successful restore was cancelled');
    check(uploads.reduce((n,u)=>n+u.size,0)===total,'Not every backup byte was uploaded');
    check(operations.filter(x=>x==='restore-chunk').length===64,'Unexpected chunk count');
   }else if(mode==='wrong-size'){
    check(!calls.length&&!uploads.length,'Wrong-size backup reached the device');
   }else{
    check(operations.at(-1)==='restore-cancel','Failed/cancelled restore kept a device session');
    check(!operations.includes('restore-finish'),'Partial restore committed the bootloader');
   }
   check(!activeRestore&&!cancelRestore&&!localBusy,'Frontend state leaked');
   results.push({case:mode,uploads:uploads.length,largest_upload:Math.max(0,...uploads.map(u=>u.size)),
                 task_count:calls.length,last_task:operations.at(-1)||null});
  }
  return JSON.stringify({scope:'Actual browser frontend with in-page write API fixtures; no device access',results});
 }finally{
  task=savedTask;transfer=savedTransfer;
  if(savedFiles)Object.defineProperty(input,'files',savedFiles);else delete input.files;
  remoteBusy=false;localBusy=false;serverRestore=0;activeRestore=0;cancelRestore=false;controls();
 }
})()
