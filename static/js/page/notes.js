NB.openVersionHistory=function(){var e=NB.currentNote||NB.state&&NB.state.currentNote;if(e){var t=e.id||e.note_uid||e.uid;t?VersionHistory.open("note",String(t),function(e){var t=document.getElementById("nbContentInput")||document.querySelector(".nb-content-input")||document.querySelector("[contenteditable]");t&&("TEXTAREA"===t.tagName||"INPUT"===t.tagName?t.value=e:t.innerHTML=e,"function"==typeof NB.onContentInput&&NB.onContentInput(e)),alert("已回滚到该版本，请点击保存同步")}):alert("无法获取笔记ID")}else alert("请先选择一篇笔记")},function(){var e=NB.toggleComplete;NB.toggleComplete=function(){e(),n()};var t=NB.openNote;function n(){var e=NB.state&&NB.state.currentNoteId?NB.state.notes.find(function(e){return e.id===NB.state.currentNoteId}):null,t=document.getElementById("nbCompleteBtn");t&&e&&(e.completed?(t.classList.add("completed"),t.title="标记为未完成"):(t.classList.remove("completed"),t.title="标记完成"));var n=document.querySelector(".nb-content-preview")||document.querySelector(".nb-preview-content");n&&e&&(e.completed?n.classList.add("completed"):n.classList.remove("completed"))}NB.openNote=function(e){t(e),setTimeout(n,50)},"loading"===document.readyState?document.addEventListener("DOMContentLoaded",function(){setTimeout(n,100)}):setTimeout(n,100)}(),NB.takePhoto=function(){var e=document.getElementById("nbCameraInput");e&&e.click()},document.addEventListener("DOMContentLoaded",function(){var e=document.getElementById("nbCameraInput");e&&e.addEventListener("change",function(t){var n=t.target.files[0];if(n){var o=new FileReader;o.onload=function(e){var t=new Image;t.onload=function(){var e=document.createElement("canvas"),n=Math.min(1,1920/t.width);e.width=t.width*n,e.height=t.height*n,e.getContext("2d").drawImage(t,0,0,e.width,e.height);var o=e.toDataURL("image/jpeg",.8);NB.insertImageFromDataUrl(o)},t.src=e.target.result},o.readAsDataURL(n)}e.value=""})}),NB.insertImageFromDataUrl=function(e){var t=document.querySelector(".nb-content-textarea");if(t){var n=t.selectionStart,o=t.value,a="\n![图片]("+e+")\n";t.value=o.substring(0,n)+a+o.substring(n),t.selectionStart=t.selectionEnd=n+a.length,NB.onContentInput(),window.showToast&&showToast("图片已插入")}};

;(function(){
  function getCurrentContent(){
    var ta=document.getElementById('nbContentTextarea');
    if(ta&&ta.value) return ta.value;
    var n=NB.currentNote||(NB.state&&NB.state.currentNote)||null;
    if(!n&&NB.state&&NB.state.notes&&NB.state.currentNoteId){n=NB.state.notes.find(function(x){return x.id===NB.state.currentNoteId;});}
    return (n&&(n.content||n.body))||'';
  }
  function toast(msg){ if(window.showToast) showToast(msg); else alert(msg); }
  function extractTables(md){
    var lines=md.split(/\r?\n/),blocks=[],cur=[];
    function flush(){ if(cur.length>=2) blocks.push(cur.join('\n')); cur=[]; }
    for(var i=0;i<lines.length;i++){
      var l=lines[i].trim();
      if(l.charAt(0)==='|'&&l.charAt(l.length-1)==='|'&&l.length>1) cur.push(lines[i]);
      else flush();
    }
    flush();
    return blocks;
  }
  function splitRow(line){ return line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(function(x){return x.trim();}); }
  function isSep(cells){ return cells.length>0&&cells.every(function(c){return /^:?-{2,}:?$/.test(c.replace(/\s/g,''));}); }
  function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function inline(s){ s=esc(s); s=s.replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>'); s=s.replace(/`([^`]+)`/g,'<code>$1</code>'); s=s.replace(/\*([^*]+)\*/g,'<em>$1</em>'); return s; }
  function tablesToHtml(blocks){
    var tb='border-collapse:collapse;margin:8px 0;font-family:Arial,"Microsoft YaHei",sans-serif;font-size:13px;color:#1d1d1f;';
    var cs='border:1px solid #d2d2d7;padding:6px 10px;text-align:left;vertical-align:top;';
    var hs=cs+'background:#f2f3f5;font-weight:600;';
    var html='';
    blocks.forEach(function(b){
      var rows=b.split(/\r?\n/).map(splitRow),head=false;
      html+='<table style="'+tb+'">';
      rows.forEach(function(cells){
        if(isSep(cells)) return;
        if(!head){ html+='<thead><tr>'+cells.map(function(c){return '<th style="'+hs+'">'+inline(c)+'</th>';}).join('')+'</tr></thead><tbody>'; head=true; }
        else html+='<tr>'+cells.map(function(c){return '<td style="'+cs+'">'+inline(c)+'</td>';}).join('')+'</tr>';
      });
      html+='</tbody></table><br>';
    });
    return html;
  }
  async function writeRich(html,text){
    try{
      if(navigator.clipboard&&window.ClipboardItem){
        await navigator.clipboard.write([new ClipboardItem({
          'text/html':new Blob([html],{type:'text/html'}),
          'text/plain':new Blob([text],{type:'text/plain'})
        })]);
        return 'rich';
      }
    }catch(e){ console.warn('富文本复制失败',e); }
    try{ await navigator.clipboard.writeText(text); return 'text'; }catch(e){}
    try{
      var ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';
      document.body.appendChild(ta);ta.select();var ok=document.execCommand('copy');document.body.removeChild(ta);
      return ok?'text':'fail';
    }catch(e){ return 'fail'; }
  }
  NB.copyTables=async function(){
    var md=getCurrentContent(),blocks=extractTables(md);
    if(!blocks.length){ toast('当前笔记没有表格'); return; }
    var html=tablesToHtml(blocks),text=blocks.join('\n\n');
    var r=await writeRich(html,text);
    if(r==='fail') alert('复制失败，请手动选择文本复制');
    else toast('已复制 '+blocks.length+' 个表格，可直接粘贴到邮件 / Word / 飞书');
  };
  NB.copyChart=async function(){
    try{
      var resp=await fetch('/api/cr/status-note-chart');
      if(!resp.ok){ alert('该笔记暂无关联的 CR 趋势图。\n请在 CR 分析页生成趋势图后，再点「同步状态笔记」。'); return; }
      var blob=await resp.blob();
      if(!blob||blob.size<100){ alert('趋势图为空，请先在 CR 分析页生成趋势图'); return; }
      await navigator.clipboard.write([new ClipboardItem({'image/png':blob})]);
      toast('CR 趋势图已复制，可直接粘贴到邮件 / 文档');
    }catch(e){
      alert('复制图片失败：'+e.message+'\n（需在 localhost/HTTPS 下使用，且浏览器支持剪贴板图片）');
    }
  };
})();
