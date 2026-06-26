import { useState, useEffect, useCallback } from "react";
import { listTasks, getConfig, getConfigStatus, type Task, type AppConfig, subscribeEvents, getHealth } from "./api";
import Sidebar from "./components/Sidebar";
import AnalysisView from "./components/AnalysisView";
import HistoryView from "./components/HistoryView";
import ConfigView from "./components/ConfigView";
import TaskDetail from "./components/TaskDetail";
import SetupDialog from "./components/SetupDialog";

type View = "analysis" | "history" | "config";

export default function App() {
  const [currentView, setCurrentView] = useState<View>("analysis");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [health, setHealth] = useState<{ ok: boolean; tasks: number; queue_size: number } | null>(null);
  const [configReady, setConfigReady] = useState<boolean | null>(null);
  const [taskEvents, setTaskEvents] = useState<Record<string, unknown[]>>({});

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
    // Check if remote is configured
    getConfigStatus()
      .then(status => setConfigReady(status.configured))
      .catch(() => setConfigReady(true)); // If can't check, assume configured
    refreshTasks();
    refreshConfig();
    const interval = setInterval(refreshTasks, 3000);
    return () => clearInterval(interval);
  }, [refreshTasks, refreshConfig]);

  const handleTaskCreated = useCallback((taskId: string) => {
    const unsub = subscribeEvents(taskId, (event: any) => {
      setTaskEvents((prev) => ({
        ...prev,
        [taskId]: [...(prev[taskId] || []), event],
      }));
      if (event.event === "task_completed" || event.event === "task_failed") {
        refreshTasks();
      }
    });
    setTimeout(() => {
      refreshTasks().then(() => {
        const t = tasks.find((x) => x.id === taskId);
        if (t) setSelectedTask(t);
      });
    }, 500);
    return unsub;
  }, [refreshTasks, tasks]);

  const handleSelectTask = useCallback(async (taskId: string) => {
    const { getTask } = await import("./api");
    try {
      const t = await getTask(taskId);
      setSelectedTask(t);
      setCurrentView("analysis");
    } catch { /* ignore */ }
  }, []);

  const handleDeleteTask = useCallback(async (taskId: string) => {
    const { deleteTask } = await import("./api");
    try {
      await deleteTask(taskId);
      if (selectedTask?.id === taskId) setSelectedTask(null);
      refreshTasks();
    } catch { /* ignore */ }
  }, [selectedTask, refreshTasks]);

  if (configReady === null) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", background: "#0f0f23", color: "#8888aa" }}>
        <p>加载中...</p>
      </div>
    );
  }

  if (configReady === false) {
    return <SetupDialog onComplete={() => setConfigReady(true)} />;
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        currentView={currentView}
        onViewChange={setCurrentView}
        tasks={tasks}
        onSelectTask={handleSelectTask}
        config={config}
        health={health}
      />
      <main className="flex-1 flex overflow-hidden">
        <div className="flex-1 overflow-auto p-6">
          {currentView === "analysis" && (
            <AnalysisView
              onTaskCreated={handleTaskCreated}
              tasks={tasks}
              onSelectTask={setSelectedTask}
            />
          )}
          {currentView === "history" && (
            <HistoryView
              tasks={tasks}
              onSelectTask={handleSelectTask}
              onDeleteTask={handleDeleteTask}
            />
          )}
          {currentView === "config" && <ConfigView config={config} onRefresh={refreshConfig} />}
        </div>
        {selectedTask && (
          <aside className="w-[420px] border-l border-gray-800 overflow-auto">
            <TaskDetail
              task={selectedTask}
              events={taskEvents[selectedTask.id] || []}
              onClose={() => setSelectedTask(null)}
            />
          </aside>
        )}
      </main>
    </div>
  );
}
