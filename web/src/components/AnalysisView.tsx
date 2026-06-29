import UploadPanel from "./UploadPanel";
import ActiveAnalysisWorkspace from "./ActiveAnalysisWorkspace";
import type { Task } from "../api";

interface AnalysisViewProps {
  activeTask: Task | null;
  onTaskCreated: (tasks: Task[]) => void;
  onCloseActiveTask: () => void;
}

export default function AnalysisView({ activeTask, onTaskCreated, onCloseActiveTask }: AnalysisViewProps) {
  if (activeTask) {
    return <ActiveAnalysisWorkspace task={activeTask} onClose={onCloseActiveTask} />;
  }

  return <UploadPanel onTaskCreated={onTaskCreated} />;
}
