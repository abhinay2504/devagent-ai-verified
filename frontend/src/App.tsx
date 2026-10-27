import { useEffect, useState } from 'react';
import { Activity, Bot, Check, ChevronRight, CircleAlert, Code2, FileCode2, FlaskConical, GitBranch, LoaderCircle, Play, Plus, RefreshCw, ShieldCheck, Sparkles, Terminal, X } from 'lucide-react';
import { api, Task, TestResult } from './api';

export default function App() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [active, setActive] = useState<Task | null>(null);
  const [description, setDescription] = useState('Add a function called is_even(number) to math_utils.py and add unit tests for positive, negative, and zero values.');
  const [repo, setRepo] = useState('sample-python-project');
  const [model, setModel] = useState<{available:boolean;model:string;message:string} | null>(null);
  const [events, setEvents] = useState<{id:number;event_type:string;message:string;created_at:string}[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [latestTest, setLatestTest] = useState<TestResult | null>(null);

  async function refresh() {
    try {
      const [taskData, modelData] = await Promise.all([api.tasks(), api.modelStatus()]);
      setTasks(taskData.tasks);
      setModel(modelData);
      if (active) {
        const detail = await api.task(active.id);
        setActive(detail);
        const ev = await api.events(active.id);
        setEvents(ev.events);
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Unable to reach backend'); }
  }
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 7000); return () => window.clearInterval(timer); }, [active?.id]);

  async function create() {
    setLoading(true); setError(''); setNotice(''); setLatestTest(null); setEvents([]);
    try { const task = await api.createTask(description, repo); setActive(task); await refresh(); setNotice('Task created. Start it when Ollama is ready.'); }
    catch (e) { setError(e instanceof Error ? e.message : 'Task creation failed'); }
    finally { setLoading(false); }
  }
  async function start() {
    if (!active) return; setLoading(true); setError(''); setNotice('');
    try { const result = await api.startTask(active.id); setNotice(result.summary); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Agent run failed'); await refresh(); }
    finally { setLoading(false); }
  }
  async function approve(yes:boolean) {
    if (!active?.patches?.length) return;
    const patch = active.patches.find(p => p.status === 'pending'); if (!patch) return;
    setLoading(true); setError('');
    try { const result = await api.approve(patch.id, yes); setNotice(`Patch ${result.status}.`); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Approval failed'); }
    finally { setLoading(false); }
  }
  async function runTests() {
    if (!active) return; setLoading(true); setError('');
    try { const result = await api.runTests(active.id); setLatestTest(result); setNotice(result.passed ? 'Tests passed.' : 'Tests failed; review output.'); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Test run failed'); }
    finally { setLoading(false); }
  }
  async function repair() {
    if (!active) return; setLoading(true); setError(''); setNotice('');
    try { const result = await api.repair(active.id); setNotice(result.summary); await refresh(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Repair proposal failed'); await refresh(); }
    finally { setLoading(false); }
  }
  const pendingPatch = active?.patches?.find(p => p.status === 'pending');
  const applied = active?.status === 'applied';

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Bot size={22}/></div><div><strong>DevAgent <span>AI</span></strong><small>SOFTWARE ENGINEER</small></div></div>
      <div className="side-label">WORKSPACE</div>
      <button className="nav-item active"><Code2 size={17}/> Agent workspace</button>
      <button className="nav-item" onClick={() => void refresh()}><Activity size={17}/> Refresh activity</button>
      <div className="side-divider"/>
      <div className="side-heading"><span>Recent tasks</span><button className="icon-button" onClick={() => {setActive(null);setLatestTest(null);setEvents([]);setNotice('');setError('');}} title="New task"><Plus size={16}/></button></div>
      <div className="task-list">{tasks.map(t => <button key={t.id} className={`task-link ${active?.id===t.id?'selected':''}`} onClick={() => {setActive(t);setLatestTest(null);setEvents([]);}}><span className={`status-dot ${t.status}`}/><span className="task-link-text">{t.description}</span></button>)}{!tasks.length && <p className="empty-small">Your tasks will appear here.</p>}</div>
      <div className="sidebar-bottom"><div className="local-badge"><span className="pulse"/><div><strong>Local-first mode</strong><small>Your model runs on your machine</small></div></div><small className="version">DEVAGENT AI · PREVIEW</small></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div className="crumb"><span>Workspace</span><ChevronRight size={14}/><strong>{active ? 'Task details' : 'New task'}</strong></div><div className="top-actions"><span className={`model-pill ${model?.available?'online':'offline'}`}><span className="status-dot"/>{model?.available ? `Model ready · ${model.model}` : 'Model not connected'}</span><button className="icon-button" onClick={() => void refresh()} title="Refresh"><RefreshCw size={16}/></button></div></header>
      <div className="content-wrap">
        <section className="hero"><div className="eyebrow"><Sparkles size={14}/> AUTONOMOUS ENGINEERING WORKFLOW</div><h1>Build better software,<br/><span>with an AI engineer.</span></h1><p>Describe a coding task. DevAgent inspects your repository, proposes a reviewable patch, and verifies it with tests after you approve.</p><div className="hero-points"><span><ShieldCheck size={15}/> Human approval</span><span><GitBranch size={15}/> Reviewable diffs</span><span><FlaskConical size={15}/> Test verification</span></div></section>
        {(error || notice) && <div className={`alert ${error?'error':'success'}`}>{error?<CircleAlert size={17}/>:<Check size={17}/>}<span>{error || notice}</span><button onClick={() => {setError('');setNotice('');}}><X size={15}/></button></div>}
        <div className="grid-layout">
          <section className="panel task-panel"><div className="panel-title"><div><span className="step-number">01</span><div><h2>{active ? 'Task overview' : 'Create an engineering task'}</h2><p>{active ? `Created ${new Date(active.created_at).toLocaleString()}` : 'Be specific about the desired change and acceptance criteria.'}</p></div></div><span className={`tag ${active?.status || 'draft'}`}>{active?.status?.replaceAll('_',' ') || 'draft'}</span></div>
            {!active ? <><label htmlFor="task">Task description</label><textarea id="task" value={description} onChange={e=>setDescription(e.target.value)} rows={5} placeholder="Describe the code change and how to verify it..."/><label htmlFor="repo">Repository inside workspace</label><input id="repo" value={repo} onChange={e=>setRepo(e.target.value)} placeholder="sample-python-project"/><p className="field-help">Use a folder under the configured workspace root. Start with the included sample project.</p><button className="primary-button" onClick={() => void create()} disabled={loading || description.trim().length<8 || !repo.trim()}><Plus size={17}/> Create task <ChevronRight size={16}/></button></> : <><div className="task-description">{active.description}</div><div className="meta-grid"><div><small>Repository</small><strong>{active.repo_path}</strong></div><div><small>Task ID</small><strong className="mono">{active.id.slice(0,8)}…</strong></div></div>{active.error && <div className="error-box">{active.error}</div>}<div className="action-row">{['queued','failed'].includes(active.status) && <button className="primary-button" onClick={() => void start()} disabled={loading}><Play size={16}/>{loading?'Working…':'Start agent'}</button>}{pendingPatch && <><button className="primary-button" onClick={() => void approve(true)} disabled={loading}><Check size={16}/> Approve patch</button><button className="secondary-button" onClick={() => void approve(false)} disabled={loading}><X size={16}/> Reject</button></>}{applied && <button className="primary-button" onClick={() => void runTests()} disabled={loading}><FlaskConical size={16}/>{loading?'Running…':'Run tests'}</button>}{active.status==='needs_review' && <button className="secondary-button" onClick={() => void repair()} disabled={loading}><RefreshCw size={16}/> Propose repair</button>}</div><p className="field-help">{active.status==='awaiting_approval'?'Review the proposed diff before applying it.':active.status==='applied'?'Patch applied. Run tests in the isolated Docker runner.':active.status==='completed'?'Task completed and tests passed.':'Changes are never applied without your approval.'}</p>{active.plan?.length ? <div className="plan-list"><strong>Implementation plan</strong>{active.plan.map((step,i)=><div className="plan-step" key={i}><span>{String(i+1).padStart(2,'0')}</span><div><b>{step.step}</b><small>{step.validation}</small></div></div>)}</div> : null}</>}
          </section>
          <section className="panel model-panel"><div className="panel-title"><div><span className="step-number">02</span><div><h2>Runtime status</h2><p>Local model and execution environment</p></div></div></div><div className="runtime-item"><div className="runtime-icon"><Bot size={18}/></div><div className="runtime-copy"><strong>Ollama model</strong><small>{model?.message || 'Checking local model...'}</small></div><span className={`mini-status ${model?.available?'good':'bad'}`}>{model?.available?'READY':'CHECK'}</span></div><div className="runtime-item"><div className="runtime-icon"><Terminal size={18}/></div><div className="runtime-copy"><strong>Test runner</strong><small>Docker required for isolated test execution</small></div><span className="mini-status neutral">DOCKER</span></div><div className="safety-note"><ShieldCheck size={17}/><p><strong>Safety by design</strong><br/>The model cannot run arbitrary shell commands. File edits require your approval. Tests use a fixed command.</p></div><button className="text-button" onClick={() => window.open('http://127.0.0.1:8000/docs','_blank')}>Open API documentation <ChevronRight size={14}/></button></section>
          <section className="panel wide-panel"><div className="panel-title"><div><span className="step-number">03</span><div><h2>Execution timeline</h2><p>Auditable events from the active task</p></div></div><Activity size={18} className="muted-icon"/></div>{events.length ? <div className="timeline">{events.map(ev=><div className="timeline-item" key={ev.id}><span className="timeline-dot"/><div><div className="timeline-heading"><strong>{ev.event_type.replaceAll('_',' ')}</strong><time>{new Date(ev.created_at).toLocaleTimeString()}</time></div><p>{ev.message}</p></div></div>)}</div>:<div className="empty-state"><div className="empty-icon"><Activity size={22}/></div><strong>No execution events yet</strong><p>Create a task and start the agent to see the workflow here.</p></div>}</section>
          <section className="panel wide-panel"><div className="panel-title"><div><span className="step-number">04</span><div><h2>Patch review</h2><p>Inspect exactly what will change before approving</p></div></div><FileCode2 size={18} className="muted-icon"/></div>{active?.patches?.length ? active.patches.map(p=><div className="patch-card" key={p.id}><div className="patch-header"><span className="file-chip"><FileCode2 size={14}/> Proposed diff</span><span className={`tag ${p.status}`}>{p.status}</span></div><pre className="diff-view">{p.diff_text.split('\n').map((line,i)=><span key={i} className={line.startsWith('+')?'diff-add':line.startsWith('-')?'diff-remove':line.startsWith('@@')?'diff-hunk':''}>{line}{'\n'}</span>)}</pre></div>):<div className="empty-state"><div className="empty-icon"><FileCode2 size={22}/></div><strong>No patch to review</strong><p>The agent's proposed file changes will appear here after planning.</p></div>}</section>
          <section className="panel wide-panel"><div className="panel-title"><div><span className="step-number">05</span><div><h2>Verification results</h2><p>Tests are the evidence of completion</p></div></div><FlaskConical size={18} className="muted-icon"/></div>{latestTest ? <div className="test-result"><div className={`test-banner ${latestTest.passed?'pass':'fail'}`}>{latestTest.passed?<Check size={18}/>:<CircleAlert size={18}/>}<strong>{latestTest.passed?'Tests passed':'Tests failed'}</strong><span>{latestTest.runner} · exit {latestTest.exit_code ?? 'timeout'}</span></div><pre className="terminal-output">{latestTest.output || 'No output returned.'}</pre></div>:active?.test_results?.length ? <pre className="terminal-output">{active.test_results[0].output || 'No output returned.'}</pre>:<div className="empty-state"><div className="empty-icon"><FlaskConical size={22}/></div><strong>Waiting for verification</strong><p>After approving a patch, run the test suite to validate the changes.</p></div>}</section>
        </div>
        <footer className="footer"><span>DevAgent AI <span className="footer-dot">•</span> Local-first prototype</span><span><ShieldCheck size={13}/> Human-in-the-loop by default</span></footer>
      </div>
    </main>
    {loading && <div className="loading-indicator"><LoaderCircle size={16}/> Processing task…</div>}
  </div>;
}
