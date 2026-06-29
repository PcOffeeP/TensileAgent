import { useState, useEffect, useCallback, useMemo } from "react";
import { listTasks, getConfig, getConfigStatus, deleteTask, type Task, type AppConfig, getHealth } from "./api";
import Sidebar from "./components/Sidebar";
import AnalysisView from "./components/AnalysisView";
import HistoryView from "./components/HistoryView";
import ConfigView from "./components/ConfigView";
import SetupDialog from "./components/SetupDialog";

type View = "analysis" | "history" | "config";

export default function App() {
  const [currentView, setCurrentView] = useState<View>("analysis");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; tasks: number; queue_size: number } | null>(null);
  const [configReady, setConfigReady] = useState<boolean | null>(null);
  const [reconfiguring, setReconfiguring] = useState(false);

  const refreshTasks = useCallback(async () => {
    try {
      const t = await listTasks();
      setTasks(t);
    } catch { /* ignore */ }
  }, []);

  const refreshConfig = useCallback(async () => {
    try {
      setConfig(await getConfig());
      setHealth(await getHealth());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    getConfigStatus()
      .then(status => setConfigReady(status.configured))
      .catch(() => setConfigReady(true));
    refreshTasks();
    refreshConfig();
    const interval = setInterval(refreshTasks, 3000);
    return () => clearInterval(interval);
  }, [refreshTasks, refreshConfig]);

  const handleTaskCreated = useCallback((newTasks: Task[]) => {
    if (newTasks.length === 0) return;
    setTasks(prev => {
      const next = [...prev];
      newTasks.forEach(t => {
        const idx = next.findIndex(x => x.id === t.id);
        if (idx >= 0) next[idx] = t;
        else next.unshift(t);
      });
      return next;
    });
    setActiveTaskId(newTasks[0].id);
    setCurrentView("analysis");
  }, []);


  const handleDeleteTask = useCallback(async (taskId: string) => {
    try {
      await deleteTask(taskId);
      if (activeTaskId === taskId) setActiveTaskId(null);
      refreshTasks();
    } catch { /* ignore */ }
  }, [activeTaskId, refreshTasks]);

  const activeTask = useMemo(() => tasks.find(t => t.id === activeTaskId) || null, [tasks, activeTaskId]);

  if (configReady === null) {
    return (
      <div className="flex items-center justify-center h-screen bg-[#FAF9F6] text-slate-500">
        <p>加载中...</p>
      </div>
    );
  }

  if (configReady === false) return <SetupDialog onComplete={() => setConfigReady(true)} />;
  if (reconfiguring) return <SetupDialog mode="reconfigure" onComplete={() => { setReconfiguring(false); setCurrentView("config"); refreshConfig(); }} />;

  return (
    <div className="flex h-screen overflow-hidden bg-[#FAF9F6]">
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        config={config}
        health={health}
      />
      <main className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-auto p-6">
          {currentView === "analysis" && (
            <AnalysisView
              activeTask={activeTask}
              onTaskCreated={handleTaskCreated}
              onCloseActiveTask={() => setActiveTaskId(null)}
            />
          )}
          {currentView === "history" && (
            <HistoryView
              tasks={tasks}
              onDeleteTask={handleDeleteTask}
            />
          )}
          {currentView === "config" && <ConfigView config={config} onRefresh={refreshConfig} onReconfigure={() => setReconfiguring(true)} />}
        </div>
      </main>
    </div>
  );
}
