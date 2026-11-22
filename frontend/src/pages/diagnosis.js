import {feedback} from '../components/common/fields.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {STATUS} from '../constants/enums.js';
import {handler, poll} from '../hooks/action.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date, value} from '../utils/format.js';

const finished = item => item.status === 'complete' || item.status === 'failed';

function progressText(job) {
  const progress = job.progress;
  if (!progress) return `第 ${job.attempt} 轮求解中。`;
  if (progress.phase === 'discard') return `第 ${job.attempt} 轮续算：已证明无解，正在核对至少舍弃哪些观测。`;
  const parts = [`第 ${job.attempt} 轮续算`];
  if (progress.k != null) parts.push(`正枚举 ${progress.k} 处断点`);
  if (progress.visited != null) parts.push(`已检查 ${progress.visited} 组`);
  if (progress.excluded != null) parts.push(`剪枝排除 ${progress.excluded} 组`);
  return `${parts.join('，')}。已排除的组合不会重查。`;
}

function membershipList(items) {
  return items.length
    ? el('div',{class:'breakpoint-list'},items.map(item=>
        el('span',{class:'breakpoint'},`${item.segment_id}（${item.node_a}—${item.node_b}）`)))
    : p('无','empty');
}

function explainedPanels(result) {
  const trace = result.trace;
  return [
    panel('断点归属',
      el('div',{class:'membership'},
        el('div',{},h(3,'每套方案都含'),membershipList(result.core)),
        el('div',{},h(3,'仅部分方案出现'),membershipList(result.optional))),
      p('「每套方案都含」是必须更换或抢修的线路；「仅部分方案」可按现场排查条件任选其一。','subtle')),
    panel(`最优方案（共 ${result.solution_count} 套）`,
      table([
        {key:'index',label:'方案'},
        {label:'断点线路',render:row=>row.breakpoints.join('、') || '（无）'},
        {key:'count',label:'断点数'},
      ],result.solutions,{caption:'最优断点方案'}),
      result.solutions_truncated && p(`已枚举全部最优方案，表格展示前 ${result.solutions.length} 套。`,'subtle')),
    panel('可复算方案 · 方案一',
      p(`断点：${trace.breakpoints.map(item=>item.segment_id).join('、') || '无'}。逐灯核对下表，或用下方复算工具任选断点重算。`),
      table([
        {key:'site_id',label:'灯组'}, {key:'node',label:'节点'}, {key:'observed',label:'夜巡观测'},
        {key:'simulated',label:'复算结果'}, {key:'match',label:'是否符合'}, {key:'witness',label:'依据'},
      ],trace.lamps,{caption:'方案一复算明细'})),
  ];
}

function unsatPanels(result) {
  const unsat = result.unsat;
  const first = unsat.sets[0];
  return panel('至少舍弃的观测',
    p('以下每套舍弃方案都能让其余观测算通，舍弃条数已是最少。'),
    table([
      {key:'index',label:'方案'},
      {label:'舍弃观测',render:row=>row.drop.map(item=>`${item.site_id}（${item.observed}）`).join('、')},
      {key:'count',label:'舍弃条数'},
    ],unsat.sets,{caption:'最少舍弃方案'}),
    p(`算通证明：舍弃「${first.drop.map(item=>item.site_id).join('、')}」后保留 ${unsat.proof.kept} 条观测，`
      + `最少 ${unsat.proof.breakpoint_count} 处断点（${unsat.proof.breakpoints.join('、') || '无'}）即可解释。`));
}

function verifyOutcome(result) {
  const verdict = result.explained
    ? `能解释全部 ${result.observed_count} 条观测（${result.breakpoint_count} 处断点`
      + `${result.optimum != null ? `，最优为 ${result.optimum} 处` : ''}）。`
    : `不能解释全部观测：${result.mismatches.join('、')} 与观测不符。`;
  return el('div',{class:'verify-result'},
    p(verdict,result.explained ? 'subtle' : 'feedback'),
    table([
      {key:'site_id',label:'灯组'}, {key:'node',label:'节点'}, {key:'observed',label:'夜巡观测'},
      {key:'simulated',label:'复算结果'}, {key:'match',label:'是否符合'},
    ],result.lamps,{caption:'复算明细'}));
}

function verifyPanel(job) {
  if (!job.catalog?.segments?.length) return null;
  const message = feedback();
  const outcome = el('div',{class:'verify-outcome'});
  const submit = button('复算这组断点',{type:'submit',class:'primary','data-testid':'verify-submit'});
  const boxes = job.catalog.segments.map(segment =>
    el('label',{class:'check'},el('input',{type:'checkbox',name:'breakpoint',value:segment.segment_id}),
      `${segment.segment_id}（${segment.node_a}—${segment.node_b}）`
      + `${segment.switch_id ? ` · 开关 ${segment.switch_id} ${segment.switch_state}` : ''}`));
  const form = el('form',{class:'fields',onSubmit:handler(submit,message,async event=>{
    const chosen = new FormData(event.target).getAll('breakpoint');
    outcome.replaceChildren(verifyOutcome(await workspace.verifyDiagnosis(job.id,chosen)));
  })},el('fieldset',{class:'breakpoint-picker'},el('legend',{},'选择断点线路'),boxes),
    el('div',{class:'actions'},submit),message,outcome);
  return panel('复算工具',p('按发起时的接线、开关和观测快照复算任意断点组合，不受后续补录影响。','subtle'),form);
}

export async function diagnosisPage(route, refresh) {
  const {spec} = workspace;
  const cs = spec.circuit;
  const jobs = await workspace.diagnoses();
  const id = route.id || jobs[0]?.id;
  if (!id) return panel(cs.pages[2],empty('还没有可查看的测算结果。','#diagnose','前往测算'));
  const job = await workspace.getDiagnosis(id);
  const sets = await workspace.circuitSets();
  const source = sets.find(item => item.id === job.circuit_set_id);
  const message = feedback();
  if (!finished(job)) {
    const original = location.hash;
    const status = el('p',{role:'status'},progressText(job));
    poll(async ()=>{
      const current = await workspace.getDiagnosis(id);
      if (status.isConnected) status.textContent = progressText(current);
      return current;
    },finished,()=>location.hash===original)
      .then(result=>{if (result && status.isConnected && location.hash===original) refresh();
        else if(status.isConnected) status.textContent='仍在执行，请点击刷新检查。';})
      .catch(error=>{if(status.isConnected) status.textContent=error.message;});
    return panel(job.name,pill(STATUS[job.status],job.status),status,
      p('求解超时会自动排队续算，已排除的断点组合不会重查。','subtle'),
      button('刷新',{class:'quiet',onClick:refresh}));
  }
  const download = job.has_export && button('下载结果 CSV',{class:'quiet','data-testid':'export',onClick:event=>
    handler(download,message,()=>workspace.download(`/diagnoses/${job.id}/export`,`breakpoint-diagnosis-${job.id}.csv`))(event)});
  const history = el('label',{class:'field run-picker',for:'diagnosis-picker'},el('span',{},'切换测算记录'),
    el('select',{id:'diagnosis-picker',onChange:event=>{location.hash=`#diagnosis/${event.target.value}`;}},
      (jobs.some(item=>item.id===job.id) ? jobs : [job,...jobs]).map(item=>
        el('option',{value:item.id,selected:item.id===job.id},item.name))));
  const result = job.result;
  const analysis = !result
    ? panel(job.name,pill(STATUS[job.status],job.status),p(job.error,'feedback'),
        link('返回调整参数',`#diagnose/${job.circuit_set_id}`,{class:'quiet'}))
    : el('section',{class:'analysis','data-testid':'diagnosis-complete'},
        el('div',{class:'result-head'},p(job.name,'eyeline'),h(2,result.headline),p(result.note,'intro-copy'),
          el('div',{class:'actions'},pill(STATUS[job.status],job.status),download,message)),
        metrics(result.metrics),
        result.verdict === 'explained' && explainedPanels(result),
        result.verdict === 'unsat' && unsatPanels(result),
        result.verdict === 'over_limit' && panel('下一步',p('提高断点搜索上限重新发起测算，或核对夜巡观测是否有误。')),
        verifyPanel(job));
  const inputs = cs.params.map(param=>el('div',{},el('dt',{},param.label),el('dd',{},value(job.params[param.key]))));
  const stats = result?.stats && el('dl',{class:'dictionary'},
    el('div',{},el('dt',{},'续算轮数'),el('dd',{},result.stats.passes ?? job.attempt)),
    result.stats.visited != null && el('div',{},el('dt',{},'检查组合'),el('dd',{},result.stats.visited)),
    result.stats.excluded != null && el('div',{},el('dt',{},'剪枝排除'),el('dd',{},result.stats.excluded)),
    result.stats.elapsed_ms != null && el('div',{},el('dt',{},'求解耗时'),el('dd',{},`${(result.stats.elapsed_ms/1000).toFixed(1)} 秒`)));
  return el('div',{},el('div',{class:'two-col'},el('div',{class:'wide-panel'},analysis),
    el('aside',{class:'sidebar-panel'},panel('测算来源',history,
      source && link(source.name,`#circuit/${source.id}`),p(date(job.finished_at),'subtle'),
      el('dl',{class:'dictionary'},inputs)),
      stats && panel('求解统计',stats))));
}
