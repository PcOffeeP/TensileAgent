import { useState, useRef, useCallback, useEffect } from "react";
import { Upload, FileVideo, Play, X, Activity } from "lucide-react";
import { createTask, createBatchTasks, type Task } from "../api";

interface UploadPanelProps {
  onTaskCreated: (tasks: Task[]) => void;
}

export default function UploadPanel({ onTaskCreated }: UploadPanelProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  const [videoPath, setVideoPath] = useState("");
  const [loading, setLoading] = useState(false);
  const [showBatch, setShowBatch] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const batchFileRef = useRef<HTMLInputElement>(null);

  const handleUpload = useCallback(() => fileRef.current?.click(), []);
  const handleBatchUpload = useCallback(() => batchFileRef.current?.click(), []);

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
          onTaskCreated([r]);
        } else {
          const r = await createBatchTasks(files);
          if (r.tasks.length > 0) {
            onTaskCreated(r.tasks);
          }
        }
        setFiles([]);
      } else if (videoPath.trim()) {
        const r = await createTask(undefined, videoPath.trim());
        onTaskCreated([r]);
        setVideoPath("");
      }
    } catch (e) {
      alert("创建任务失败: " + (e as Error).message);
    }
    setLoading(false);
  }, [files, videoPath, onTaskCreated]);

  return (
    <div className="h-full flex flex-col justify-center items-center gap-6 max-w-4xl mx-auto w-full pb-10">
      <div className="text-center mb-6">
        <h2 className="text-3xl font-bold text-slate-900 tracking-tight flex items-center justify-center gap-3 mb-3">
          <Activity className="w-8 h-8 text-[#002FA7]" />
          智能视频张力分析
        </h2>
        <p className="text-sm text-slate-500">上传拉伸试验视频，Agent 将自动进行推理并标记断裂区间。</p>
      </div>

      <div className="glass-panel rounded-2xl p-8 shadow-2xl flex flex-col md:flex-row gap-8 w-full border border-white/50 bg-white/70">
        {/* Left: Upload Controls */}
        <div className="flex-1 flex flex-col gap-5">
          <div className="flex flex-col gap-3">
            <button 
              onClick={handleUpload} 
              className="flex items-center justify-center gap-2 px-6 py-4 bg-white hover:bg-slate-50 border-2 border-dashed border-slate-300 hover:border-[#002FA7]/50 text-slate-700 rounded-xl text-base font-medium transition-all w-full shadow-sm"
            >
              <Upload className="w-5 h-5 text-[#002FA7]" /> 选择视频文件
            </button>
            <input ref={fileRef} type="file" accept="video/*" className="hidden" onChange={handleFileChange} />
          </div>

          <div className="flex items-center gap-2">
            <div className="flex-1 h-px bg-slate-200"></div>
            <span className="text-xs text-slate-400 font-medium px-2">或</span>
            <div className="flex-1 h-px bg-slate-200"></div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex-1 relative">
              <input
                type="text"
                placeholder="输入服务器视频绝对路径..."
                value={videoPath}
                onChange={(e) => setVideoPath(e.target.value)}
                className="w-full pl-4 pr-10 py-3 bg-white border border-slate-300 rounded-xl text-sm text-slate-900 outline-none focus:border-[#002FA7]/50 focus:ring-2 focus:ring-[#002FA7]/20 transition-all placeholder-slate-400"
              />
              {videoPath && (
                <button onClick={() => setVideoPath("")} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
                  <X className="w-4 h-4" />
                </button>
              )}
            </div>
          </div>

          {files.length > 0 && (
            <div className="space-y-2 max-h-[120px] overflow-auto custom-scrollbar mt-2 bg-slate-50/50 p-3 rounded-xl border border-slate-200">
              {files.map((f, i) => (
                <div key={i} className="flex items-center gap-3 text-sm text-slate-700 bg-white border border-slate-200 px-3 py-2 rounded-lg shadow-sm">
                  <FileVideo className="w-4 h-4 text-[#002FA7]" />
                  <span className="flex-1 truncate font-medium">{f.name}</span>
                  <button onClick={() => removeFile(i)} className="text-slate-400 hover:text-rose-500 transition-colors">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            onClick={handleStart}
            disabled={loading || (files.length === 0 && !videoPath.trim())}
            className="mt-4 flex items-center justify-center gap-2 px-6 py-3.5 bg-[#002FA7] hover:bg-[#002FA7]/90 disabled:opacity-50 disabled:hover:bg-[#002FA7] text-white rounded-xl text-base font-semibold shadow-[0_8px_20px_rgba(0,47,167,0.25)] transition-all"
          >
            {loading ? (
              <><Activity className="w-5 h-5 animate-spin" /> 准备分析中...</>
            ) : (
              <><Play className="w-5 h-5 fill-current" /> 开始分析任务</>
            )}
          </button>
        </div>

        {/* Right: Video Preview */}
        <div className="flex-1 flex flex-col md:border-l border-t md:border-t-0 border-slate-200 md:pl-8 pt-6 md:pt-0">
          <h3 className="text-xs font-semibold text-slate-400 mb-3 uppercase tracking-widest">预览</h3>
          {videoPreviewUrl ? (
            <div className="bg-slate-900 rounded-xl overflow-hidden shadow-inner flex-1 min-h-[220px] max-h-[300px] relative group">
              <video src={videoPreviewUrl} controls className="w-full h-full object-contain" />
            </div>
          ) : (
            <div className="flex-1 bg-slate-50/50 rounded-xl border-2 border-slate-200 border-dashed flex items-center justify-center flex-col gap-3 text-slate-400 min-h-[220px]">
              <FileVideo className="w-8 h-8 opacity-30" />
              <span className="text-sm">未选择视频</span>
            </div>
          )}
        </div>
      </div>

      {/* Batch Upload (Weakened) */}
      <div className="mt-4 w-full flex flex-col items-center">
        <button 
          onClick={() => setShowBatch(!showBatch)}
          className="text-xs text-slate-400 hover:text-[#002FA7] transition-colors underline underline-offset-2"
        >
          {showBatch ? "隐藏批量处理" : "需要批量处理多个视频?"}
        </button>
        
        {showBatch && (
          <div className="mt-4 p-4 bg-slate-50 border border-slate-200 rounded-xl w-full max-w-md text-center">
            <p className="text-xs text-slate-500 mb-3">批量处理模式不提供实时的过程可视化跟踪，所有任务将在后台排队执行。</p>
            <input ref={batchFileRef} type="file" multiple accept="video/*" className="hidden" onChange={handleFileChange} />
            <button 
              onClick={handleBatchUpload}
              className="px-4 py-2 bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 text-sm font-medium rounded-lg transition-colors"
            >
              选择多个文件
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
