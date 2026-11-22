import {feedback, field} from '../components/common/fields.js';
import {empty, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {STATUS} from '../constants/enums.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, link, p} from '../utils/dom.js';
import {date} from '../utils/format.js';

export async function diagnosePage(route, refresh) {
  const {spec} = workspace;
  const cs = spec.circuit;
  const sets = await workspace.circuitSets();
  const jobs = await workspace.diagnoses();
  const error = feedback();
  const submit = button(`执行${cs.run}`,{type:'submit',class:'primary','data-testid':'start-diagnosis'});
  const form = el('form',{class:'fields','data-testid':'diagnosis-form',
    onSubmit:handler(submit,error,async event=>{
      const data = new FormData(event.target);
      const item = await workspace.startDiagnosis({circuit_set_id:Number(data.get('circuit_set_id')),
        name:data.get('name'),
        params:Object.fromEntries(cs.params.map(param=>[param.key,data.get(param.key)]))});
      location.hash = `#diagnosis/${item.id}`;
    })},
    el('label',{for:'circuit-set-id',class:'field'},el('span',{},'接线批次'),
      el('select',{id:'circuit-set-id',name:'circuit_set_id',required:true},sets.map(item=>
        el('option',{value:item.id,selected:String(item.id)===String(route.id)},`${item.name} · ${item.row_count} 行`)))),
    field({key:'name',label:'测算名称',type:'string',max_length:120},`样本${cs.run}`),
    el('div',{class:'form-grid'},cs.params.map(param=>field(param))),
    el('div',{class:'actions'},submit),error);
  const jobList = table([
    {label:'测算',render:item=>link(item.name,`#diagnosis/${item.id}`)},
    {label:'状态',render:item=>pill(STATUS[item.status],item.status)},
    {label:'续算轮数',render:item=>item.attempt || '—'},
    {label:'时间',render:item=>date(item.created_at)},
  ],jobs,{caption:'断点测算记录',empty:'首次测算后将在此显示后台状态。'});
  return el('div',{class:'two-col'},el('div',{class:'wide-panel'},
    panel(cs.run,session.canWrite ? (sets.length ? form : empty('请先导入接线批次。','#circuit','前往导入'))
      : p('只读角色可以查看历史测算和诊断结果。','empty')),
    panel('测算记录',jobList)),
    el('aside',{class:'sidebar-panel'},panel('计算口径',el('ul',{class:'method-list'},cs.methodology.map(text=>el('li',{},text))))));
}
