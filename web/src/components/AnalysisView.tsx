import { useState, useRef, useCallback } from "react";
import { Upload, Folder, Play, X, FileVideo } from "lucide-react";
import { createTask, createBatchTasks, type Task } from "../api";

interface AnalysisViewProps {
  onTaskCreated: (taskId: string) => void;
  tasks: Task[];
  onSelectTask: (t: Task) => void;
}

export default function AnalysisView({ onTaskCreated, tasks, onSelectTask }: AnalysisViewProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [videoPath, setVideoPath] = useState("");
  const [loading, setLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const runningCount = tasks.filter((t) => t.status === "running" || t.status === "queued").length;

  const handleUpload = useCallback(() => fileRef.current?.click(), []);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) setFiles(Array.from(e.target.files));
  }, []);

  const removeFile = useCallback((i: number) => {
    setFiles((f) => f.filter((_, j) => j !== i));
  }, []);

  const handleStart = useCallback(async () => {
    setLoading(true);
    try {
      if (files.length > 0) {
        if (files.length === 1) {
          const r = await createTask(files[0]);
          onTaskCreated(r.task_id);
        } else {
          const r = await createBatchTasks(files);
          r.tasks.forEach((t) => onTaskCreated(t.task_id));
        }
        setFiles([]);
      } else if (videoPath.trim()) {
        const r = await createTask(undefined, videoPath.trim());
        onTaskCreated(r.task_id);
        setVideoPath("");
      }
    } catch (e) {
      alert("创建任务失败: " + (e as Error).message);
    }
    setLoading(false);
  }, [files, videoPath, onTaskCreated]);

  return (
    <div>
      <h2 className="text-xl font-bold mb-4">实验分析</h2>
      <div className="bg-gray-900 rounded-lg p-4 mb-4">
        <p className="text-sm text-gray-400 mb-3">
          {runningCount > 0 ? `队列中有 ${runningCount} 个任务` : "上传视频或输入本地路径开始分析"}
        </p>
        <div className="flex gap-2 mb-3">
          <button onClick={handleUpload} className="flex items-center gap-2 px-4 py-2 bg-gray-800 rounded hover:bg-gray-700 text-sm">
            <Upload className="w-4 h-4" /> 上传视频
          </button>
          <input ref={fileRef} type="file" multiple accept="video/*" className="hidden" onChange={handleFileChange} />
        </div>
        {files.length > 0 && (
          <div className="space-y-1 mb-3">
            {files.map((f, i) => (
              <div key={i} className="flex items-center gap-2 text-xs text-gray-400 bg-gray-800 px-3 py-1.5 rounded">
                <FileVideo className="w-3 h-3" />
                <span className="flex-1 truncate">{f.name}</span>
                <button onClick={() => removeFile(i)}><X className="w-3 h-3" /></button>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-2 mb-3">
          <input
            type="text"
            placeholder="或输入本地视频路径..."
            value={videoPath}
            onChange={(e) => setVideoPath(e.target.value)}
            className="flex-1 px-3 py-2 bg-gray-800 rounded text-sm outline-none focus:ring-1 focus:ring-cyan-400"
          />
          <button onClick={() => setVideoPath("")} className="px-2 text-gray-500 hover:text-gray-300">
            <X className="w-4 h-4" />
          </button>
        </div>
        <button
          onClick={handleStart}
          disabled={loading || (files.length === 0 && !videoPath.trim())}
          className="flex items-center gap-2 px-6 py-2 bg-cyan-600 rounded hover:bg-cyan-500 disabled:opacity-50 text-sm font-medium"
        >
          <Play className="w-4 h-4" /> {loading ? "提交中..." : "开始分析"}
        </button>
      </div>
      {tasks.filter((t) => t.status === "queued" || t.status === "running").length > 0 && (
        <div className="bg-gray-900 rounded-lg p-4">
          <h3 className="text-sm font-medium mb-2">任务队列</h3>
          <div className="space-y-1">
            {tasks.filter((t) => t.status === "queued" || t.status === "running").map((t) => (
              <div key={t.id} onClick={() => onSelectTask(t)} className="flex items-center gap-2 px-3 py-2 bg-gray-800 rounded text-xs cursor-pointer hover:bg-gray-700">
                <span className={`w-2 h-2 rounded-full ${t.status === "running" ? "bg-blue-400 animate-pulse" : "bg-yellow-400"}`} />
                <span>{t.video_id}</span>
                <span className="text-gray-500 ml-auto">{t.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
