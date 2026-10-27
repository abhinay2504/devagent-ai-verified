const API = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
  return payload as T;
}

export type Task = { id: string; description: string; repo_path: string; status: string; error?: string | null; created_at: string; plan?: {step:string;validation:string}[]; patches?: Patch[]; test_results?: TestResult[] };
export type Patch = { id: string; task_id: string; diff_text: string; status: string; created_at: string };
export type TestResult = { runner: string; passed: number | boolean; exit_code: number | null; output: string; created_at?: string };
export const api = {
  health: () => request<{status:string}>('/api/health'),
  modelStatus: () => request<{available:boolean;model:string;message:string}>('/api/model/status'),
  repositories: () => request<{workspace_root:string;repositories:string[]}>('/api/repositories'),
  tasks: () => request<{tasks:Task[]}>('/api/tasks'),
  task: (id:string) => request<Task>(`/api/tasks/${id}`),
  createTask: (description:string, repo_path:string) => request<Task>('/api/tasks', {method:'POST',body:JSON.stringify({description,repo_path})}),
  startTask: (id:string) => request<{patch_id:string;summary:string;diff:string;plan:{step:string;validation:string}[]}>(`/api/tasks/${id}/start`, {method:'POST'}),
  approve: (patchId:string, approve:boolean, feedback?:string) => request<{status:string}>(`/api/approvals/${patchId}`, {method:'POST',body:JSON.stringify({approve,feedback})}),
  runTests: (id:string) => request<TestResult>(`/api/tasks/${id}/tests`, {method:'POST'}),
  repair: (id:string) => request<{patch_id:string;summary:string;diff:string;plan:{step:string;validation:string}[]}>(`/api/tasks/${id}/repair`, {method:'POST'}),
  events: (id:string) => request<{events:{id:number;event_type:string;message:string;created_at:string}[]}>(`/api/tasks/${id}/events`),
};
