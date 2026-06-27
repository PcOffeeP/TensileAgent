import { useState, useRef, useCallback, useEffect } from "react";
import { Upload, FileVideo, Play, X, Activity, CheckCircle, AlertCircle, ChevronDown, ChevronRight, Terminal } from "lucide-react";
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
  const [expandedTasks, setExpandedTasks] = useState<Set<string>>(new Set());

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
          setExpandedTasks(prev => new Set(prev).add(r.task_id));
        } else {
          const r = await createBatchTasks(files);
          r.tasks.forEach((t) => {
            onTaskCreated(t.task_id);
            setExpandedTasks(prev => new Set(prev).add(t.task_id));
          });
        }
        setFiles([]);
        setVideoPreviewUrl(null);
      } else if (videoPath.trim()) {
        const r = await createTask(undefined, videoPath.trim());
        onTaskCreated(r.task_id);
        setExpandedTasks(prev => new Set(prev).add(r.task_id));
        setVideoPath("");
      }
    } catch (e) {
      alert("创建任务失败: " + (e as Error).message);
    }
    setLoading(false);
  }, [files, videoPath, onTaskCreated]);

  const toggleTaskExpand = (taskId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedTasks(prev => {
      const newSet = new Set(prev);
      if (newSet.has(taskId)) newSet.delete(taskId);
      else newSet.add(taskId);
      return newSet;
    });
  };

  // 始终显示最近的10个任务，包括已完成的
  const recentTasks = [...tasks].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()).slice(0, 10);

  return (
    <div className="max-w-5xl mx-auto pb-12">
      <div className="mb-8">
        <h2 className="text-2xl font-semibold text-slate-100 tracking-tight flex items-center gap-2">
          <Activity className="w-5 h-5 text-cyan-500" />
          智能视频分析
        </h2>
        <p className="text-sm text-slate-400 mt-1">上传本地视频或输入服务器视频路径进行张力与断裂点分析。</p>
      </div>

      <div className="glass-panel rounded-xl p-6 mb-8 shadow-xl">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-3">
              <button 
                onClick={handleUpload} 
                className="flex items-center justify-center gap-2 px-5 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 rounded-lg text-sm font-medium transition-colors w-full md:w-auto"
              >
                <Upload className="w-4 h-4" /> 选择视频文件
              </button>
              <input ref={fileRef} type="file" multiple accept="video/*" className="hidden" onChange={handleFileChange} />
            </div>

            {files.length > 0 && (
              <div className="space-y-2">
                {files.map((f, i) => (
                  <div key={i} className="flex items-center gap-3 text-sm text-slate-300 bg-slate-800/50 border border-slate-700/50 px-4 py-2 rounded-lg">
                    <FileVideo className="w-4 h-4 text-cyan-500" />
                    <span className="flex-1 truncate font-medium">{f.name}</span>
                    <button onClick={() => removeFile(i)} className="text-slate-500 hover:text-slate-300 transition-colors">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-center gap-2 mt-2">
              <div className="flex-1 relative">
                <input
                  type="text"
                  placeholder="或输入服务器本地视频绝对路径..."
                  value={videoPath}
                  onChange={(e) => setVideoPath(e.target.value)}
                  className="w-full pl-4 pr-10 py-2.5 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition-all placeholder-slate-500"
                />
                {videoPath && (
                  <button onClick={() => setVideoPath("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>

            <button
              onClick={handleStart}
              disabled={loading || (files.length === 0 && !videoPath.trim())}
              className="mt-4 flex items-center justify-center gap-2 px-6 py-3 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 disabled:hover:bg-cyan-600 text-white rounded-lg text-sm font-semibold shadow-lg shadow-cyan-900/20 transition-all"
            >
              {loading ? (
                <><Activity className="w-4 h-4 animate-spin" /> 正在提交分析任务...</>
              ) : (
                <><Play className="w-4 h-4" /> 开始智能分析</>
              )}
            </button>
          </div>

          <div className="flex flex-col">
            <h3 className="text-sm font-medium text-slate-400 mb-3">视频预览</h3>
            {videoPreviewUrl ? (
              <div className="bg-black rounded-lg overflow-hidden border border-slate-800 aspect-video shadow-inner">
                <video src={videoPreviewUrl} controls className="w-full h-full object-contain" />
              </div>
            ) : (
              <div className="flex-1 bg-slate-900/50 rounded-lg border border-slate-800 border-dashed flex items-center justify-center flex-col gap-2 text-slate-600 min-h-[200px]">
                <FileVideo className="w-8 h-8 opacity-50" />
                <span className="text-sm">暂无视频预览</span>
                <span className="text-xs">支持预览单文件上传</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {recentTasks.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-medium text-slate-200">任务动态</h3>
            <span className="text-xs text-slate-500">仅显示近期任务</span>
          </div>
          <div className="space-y-3">
            {recentTasks.map((t) => {
              const isRunning = t.status === "running";
              const isQueued = t.status === "queued";
              const isCompleted = t.status === "completed";
              const isFailed = t.status === "failed";
              const isExpanded = expandedTasks.has(t.id);
              const result = t.result ?? {};
              const displayStatus = (result.status as string) || t.status;

              return (
                <div 
                  key={t.id} 
                  className="glass-panel rounded-xl overflow-hidden cursor-pointer hover:border-slate-600 transition-colors"
                  onClick={() => onSelectTask(t)}
                >
                  {/* Task Header Card */}
                  <div className="px-5 py-4 flex items-center gap-4">
                    <div onClick={(e) => toggleTaskExpand(t.id, e)} className="p-1 hover:bg-slate-700 rounded text-slate-400 transition-colors">
                      {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </div>
                    
                    <div className="flex items-center justify-center w-8 h-8 rounded-full bg-slate-800 shrink-0">
                      {isRunning && <Activity className="w-4 h-4 text-cyan-400 animate-spin" />}
                      {isQueued && <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />}
                      {isCompleted && <CheckCircle className="w-4 h-4 text-emerald-400" />}
                      {isFailed && <AlertCircle className="w-4 h-4 text-rose-400" />}
                    </div>

                    <div className="flex flex-col min-w-0 flex-1">
                      <div className="flex items-center gap-3">
                        <span className="font-semibold text-slate-200 truncate">{t.video_id}</span>
                        <span className="font-mono text-xs text-slate-500 bg-slate-800/80 px-2 py-0.5 rounded">ID: {t.id.slice(0, 8)}</span>
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`text-xs font-medium ${
                          isRunning ? "text-cyan-400" :
                          isQueued ? "text-amber-400" :
                          isCompleted ? "text-emerald-400" : "text-rose-400"
                        }`}>
                          {isRunning ? "正在运行" : 
                           isQueued ? "队列中" : 
                           isCompleted ? "分析完成" : "分析失败"}
                        </span>
                        <span className="text-xs text-slate-500">
                          {t.created_at ? new Date(t.created_at).toLocaleString() : ""}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Expanded Task Details (Inline Results) */}
                  {isExpanded && (
                    <div className="px-5 pb-5 pt-2 border-t border-slate-800/50 bg-slate-900/30">
                      {isCompleted && t.result ? (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-3">
                          <div className="bg-slate-800/50 p-3 rounded-lg border border-slate-700/50">
                            <span className="text-xs text-slate-400 block mb-1">最终状态</span>
                            <span className="text-sm font-medium text-emerald-400">{displayStatus}</span>
                          </div>
                          {!!result.type && (
                            <div className="bg-slate-800/50 p-3 rounded-lg border border-slate-700/50">
                              <span className="text-xs text-slate-400 block mb-1">类型</span>
                              <span className="text-sm font-medium text-slate-200">{String(result.type)}</span>
                            </div>
                          )}
                          {!!result.location && (
                            <div className="bg-slate-800/50 p-3 rounded-lg border border-slate-700/50">
                              <span className="text-xs text-slate-400 block mb-1">断裂位置</span>
                              <span className="text-sm font-medium text-slate-200 font-mono">{String(result.location)}</span>
                            </div>
                          )}
                          {result.confidence != null && (
                            <div className="bg-slate-800/50 p-3 rounded-lg border border-slate-700/50">
                              <span className="text-xs text-slate-400 block mb-1">置信度</span>
                              <span className="text-sm font-medium text-slate-200">{Number(result.confidence).toFixed(2)}</span>
                            </div>
                          )}
                        </div>
                      ) : isFailed && t.error ? (
                        <div className="mt-3 bg-rose-950/30 border border-rose-900/50 p-4 rounded-lg text-sm text-rose-300">
                          <p className="font-semibold mb-1 flex items-center gap-2"><AlertCircle className="w-4 h-4" /> {t.error.code}</p>
                          <p className="opacity-80">{t.error.message}</p>
                        </div>
                      ) : (
                        <div className="mt-3 flex items-center gap-2 text-sm text-slate-400 py-2">
                          <Terminal className="w-4 h-4" /> 
                          {isRunning ? "分析模型正在处理该视频，请耐心等待..." : "任务正在等待调度..."}
                        </div>
                      )}
                      <div className="mt-4 flex justify-end">
                        <button 
                          onClick={(e) => { e.stopPropagation(); onSelectTask(t); }}
                          className="text-xs text-cyan-500 hover:text-cyan-400 font-medium transition-colors flex items-center gap-1"
                        >
                          查看详细日志和导出 <ChevronRight className="w-3 h-3" />
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
