import {feedback, field} from '../components/common/fields.js';
import {empty, panel} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, link, p} from '../utils/dom.js';
import {date} from '../utils/format.js';

export async function circuitPage(route, refresh) {
  const {spec} = workspace;
  const cs = spec.circuit;
  const sets = await workspace.circuitSets();
  const selected = sets.find(item => item.id === route.id) || sets[0];
  const error = feedback();
  const sample = button('下载示例 CSV', {class:'quiet', onClick:event =>
    handler(sample, error, () => workspace.download('/circuit/template', cs.sample_name))(event)});
  const detail = selected && await workspace.getCircuitSet(selected.id, route.offset);
  const columns = cs.fields.map(item => ({key:item.key, label:item.label}));
  const preview = detail ? panel('批次明细', el('div',{class:'actions'},
    el('label',{for:'circuit-set-id',class:'sr'},'选择接线批次'),
    el('select',{id:'circuit-set-id','aria-label':'选择接线批次',onChange:event=>{location.hash=`#circuit/${event.target.value}`;}},
      sets.map(item=>el('option',{value:item.id,selected:item.id===selected.id},item.name))),
    link('使用此批次测算',`#diagnose/${detail.id}`,{class:'quiet'})),
    p(`${detail.filename} · ${detail.row_count} 行 · ${date(detail.created_at)}`,'filename'),
    table(columns,detail.rows,{caption:'批次明细',pageSize:16}),
    el('div',{class:'pagination'},
      route.offset > 0 && link('上一批明细',`#circuit/${detail.id}/${Math.max(0,route.offset-16)}`,{class:'quiet'}),
      p(`${detail.rows.length ? route.offset+1 : route.offset}–${route.offset+detail.rows.length} / ${detail.row_count}`),
      route.offset+16 < detail.row_count && link('下一批明细',`#circuit/${detail.id}/${route.offset+16}`,{class:'quiet'})))
    : empty('没有可用的接线批次。请导入示例或业务 CSV。');
  const submit = button('校验并导入', {type:'submit', class:'primary'});
  const upload = session.canWrite && el('form',{class:'fields',onSubmit:handler(submit,error,async event=>{
    const data = new FormData(event.target);
    const file = data.get('source');
    if (!file?.size) throw new Error('请选择一个 CSV 文件');
    if (file.size > 2_000_000) throw new Error('CSV 最多 2 MB');
    const item = await workspace.uploadCircuit({name:data.get('batch_name'),filename:file.name,csv_text:await file.text()});
    const target = `#circuit/${item.id}`;
    if (location.hash === target) await refresh();
    else location.hash = target;
  })},field({key:'batch_name',label:'批次名称',type:'string',max_length:120}),
    el('label',{class:'field',for:'source'},el('span',{},'接线与观测 CSV'),
      el('input',{id:'source',type:'file',name:'source',accept:'.csv,text/csv',required:true})),submit);
  return el('div',{class:'two-col'},el('div',{class:'wide-panel'},preview),el('aside',{class:'sidebar-panel'},
    panel('数据导入',p('导入后保留原批次和校验指纹。补录请另存新批次导入：补录只供新测算，进行中的测算恢复时仍按发起时的接线、开关和观测。','subtle'),sample,upload,error),
    panel('字段说明',el('dl',{class:'dictionary'},cs.fields.map(item=>el('div',{},el('dt',{},item.label),
      el('dd',{},item.key,item.required === false ? ' · 可空' : ' · 必填',item.options ? ` · ${item.options.join(' / ')}` : '')))))));
}
