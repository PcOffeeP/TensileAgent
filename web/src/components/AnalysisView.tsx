import { useState, useRef, useCallback, useEffect } from "react";
import { Upload, FileVideo, Play, X, Activity, CheckCircle, AlertCircle, Clock } from "lucide-react";
import { createTask, createBatchTasks, type Task } from "../api";

interface AnalysisViewProps {
  onTaskCreated: (taskId: string) => void;
  tasks: Task[];
  onSelectTask: (t: Task) => void;
}

export default function AnalysisView({ onTaskCreated, tasks, onSelectTask }: AnalysisViewProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  const [videoPath, setVideoPath] = useState("");
  const [loading, setLoading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const handleUpload = useCallback(() => fileRef.current?.click(), []);

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const newFiles = Array.from(e.target.files);
      setFiles(newFiles);
      if (newFiles.length === 1) {
        setVideoPreviewUrl(URL.createObjectURL(newFiles[0]));
      } else {
        setVideoPreviewUrl(null);
      }
    }
  }, []);

  const removeFile = useCallback((i: number) => {
    setFiles((f) => {
      const newFiles = f.filter((_, j) => j !== i);
      if (newFiles.length === 1) {
        setVideoPreviewUrl(URL.createObjectURL(newFiles[0]));
      } else {
        setVideoPreviewUrl(null);
      }
      return newFiles;
    });
  }, []);

  // Cleanup object URLs
  useEffect(() => {
    return () => {
      if (videoPreviewUrl) URL.revokeObjectURL(videoPreviewUrl);
    };
  }, [videoPreviewUrl]);

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

  // 始终显示最近的10个任务，包括已完成的
  const recentTasks = [...tasks].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()).slice(0, 10);

  return (
    <div className="h-full flex flex-col gap-6 max-w-6xl mx-auto w-full pb-6">
      {/* Top Section: Video Upload & Preview */}
      <div className="flex-none">
        <div className="mb-4">
          <h2 className="text-xl font-semibold text-slate-900 tracking-tight flex items-center gap-2">
            <Activity className="w-5 h-5 text-[#002FA7]" />
            智能视频分析
          </h2>
          <p className="text-xs text-slate-500 mt-1">上传本地视频或输入服务器视频路径进行张力与断裂点分析。</p>
        </div>

        <div className="glass-panel rounded-xl p-5 shadow-xl flex flex-col md:flex-row gap-6">
          {/* Left: Upload Controls */}
          <div className="flex-1 flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <button 
                onClick={handleUpload} 
                className="flex items-center justify-center gap-2 px-5 py-2.5 bg-white hover:bg-slate-50 border border-slate-200 text-slate-700 rounded text-sm font-medium transition-colors w-full md:w-auto shadow-sm"
              >
                <Upload className="w-4 h-4 text-[#002FA7]" /> 选择视频文件
              </button>
              <input ref={fileRef} type="file" multiple accept="video/*" className="hidden" onChange={handleFileChange} />
            </div>

            {files.length > 0 && (
              <div className="space-y-2 max-h-[120px] overflow-auto custom-scrollbar">
                {files.map((f, i) => (
                  <div key={i} className="flex items-center gap-3 text-xs text-slate-700 bg-slate-50 border border-slate-200 px-3 py-1.5 rounded">
                    <FileVideo className="w-3.5 h-3.5 text-[#002FA7]" />
                    <span className="flex-1 truncate font-medium">{f.name}</span>
                    <button onClick={() => removeFile(i)} className="text-slate-400 hover:text-rose-500 transition-colors">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-center gap-2 mt-auto">
              <div className="flex-1 relative">
                <input
                  type="text"
                  placeholder="或输入服务器本地视频绝对路径..."
                  value={videoPath}
                  onChange={(e) => setVideoPath(e.target.value)}
                  className="w-full pl-3 pr-8 py-2 bg-white border border-slate-300 rounded text-xs text-slate-900 outline-none focus:border-[#002FA7]/50 focus:ring-1 focus:ring-[#002FA7]/50 transition-all placeholder-slate-400"
                />
                {videoPath && (
                  <button onClick={() => setVideoPath("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>

            <button
              onClick={handleStart}
              disabled={loading || (files.length === 0 && !videoPath.trim())}
              className="mt-2 flex items-center justify-center gap-2 px-6 py-2.5 bg-[#002FA7] hover:bg-[#002FA7]/90 disabled:opacity-50 disabled:hover:bg-[#002FA7] text-white rounded text-sm font-semibold shadow-[0_4px_14px_rgba(0,47,167,0.25)] transition-all"
            >
              {loading ? (
                <><Activity className="w-4 h-4 animate-spin" /> 正在提交任务...</>
              ) : (
                <><Play className="w-4 h-4" /> 开始分析</>
              )}
            </button>
          </div>

          {/* Right: Video Preview */}
          <div className="flex-1 flex flex-col md:border-l border-t md:border-t-0 border-slate-200 md:pl-6 pt-4 md:pt-0">
            <h3 className="text-xs font-semibold text-slate-500 mb-2 uppercase tracking-wider">Video Preview</h3>
            {videoPreviewUrl ? (
              <div className="bg-slate-100 rounded overflow-hidden border border-slate-200 shadow-inner flex-1 min-h-[160px] max-h-[240px]">
                <video src={videoPreviewUrl} controls className="w-full h-full object-contain" />
              </div>
            ) : (
              <div className="flex-1 bg-slate-50/50 rounded border border-slate-200 border-dashed flex items-center justify-center flex-col gap-2 text-slate-400 min-h-[160px]">
                <FileVideo className="w-6 h-6 opacity-40" />
                <span className="text-xs">暂无视频预览</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Bottom Section: Recent Tasks Data Table */}
      {recentTasks.length > 0 && (
        <div className="flex-1 flex flex-col min-h-0">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-slate-800 uppercase tracking-wider">近期任务队列</h3>
          </div>
          
          <div className="glass-panel rounded-xl overflow-auto flex-1 custom-scrollbar">
            <table className="w-full text-left border-collapse whitespace-nowrap">
              <thead className="sticky top-0 bg-white/95 backdrop-blur z-10 shadow-[0_1px_2px_rgba(0,0,0,0.05)]">
                <tr className="border-b border-slate-200 text-[11px] text-slate-500 uppercase tracking-wider">
                  <th className="px-4 py-3 font-semibold w-12 text-center">状态</th>
                  <th className="px-4 py-3 font-semibold">任务 ID</th>
                  <th className="px-4 py-3 font-semibold">视频标识</th>
                  <th className="px-4 py-3 font-semibold">结果概要</th>
                  <th className="px-4 py-3 font-semibold text-right">创建时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recentTasks.map((t) => {
                  const isRunning = t.status === "running";
                  const isQueued = t.status === "queued";
                  const isCompleted = t.status === "completed";
                  const isFailed = t.status === "failed";
                  
                  const result = t.result ?? {};
                  const displayStatus = (result.status as string) || t.status;
                  
                  let resultSummary = "--";
                  if (isCompleted && result) {
                    if (result.type) {
                      resultSummary = `${result.type}`;
                      if (result.location) resultSummary += ` @ ${result.location}`;
                    } else {
                      resultSummary = displayStatus;
                    }
                  } else if (isFailed) {
                    resultSummary = t.error?.code || "Error";
                  }

                  return (
                    <tr 
                      key={t.id} 
                      onClick={() => onSelectTask(t)}
                      className="data-table-row cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3 text-center">
                        <div className="flex justify-center">
                          {isRunning && <Activity className="w-4 h-4 text-[#002FA7] animate-spin" />}
                          {isQueued && <Clock className="w-4 h-4 text-amber-500" />}
                          {isCompleted && <CheckCircle className="w-4 h-4 text-emerald-500" />}
                          {isFailed && <AlertCircle className="w-4 h-4 text-rose-500" />}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs text-slate-500">{t.id.slice(0, 8)}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-sm text-slate-900 font-medium">{t.video_id}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs ${isFailed ? "text-rose-600 font-medium" : isCompleted ? "text-emerald-600 font-medium" : "text-slate-500"}`}>
                          {resultSummary}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className="font-mono text-xs text-slate-400">
                          {t.created_at ? new Date(t.created_at).toLocaleString() : "--"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
