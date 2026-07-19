import { useState, useRef, useCallback, useEffect } from "react";
import { Upload, FileVideo, Play, X, Activity, Pencil } from "lucide-react";
import { createTask, createBatchTasks, type Task } from "../api";

const DEFAULT_QUESTION = "这个拉伸试验视频是否发生断裂？";

interface UploadPanelProps {
  onTaskCreated: (tasks: Task[]) => void;
}

export default function UploadPanel({ onTaskCreated }: UploadPanelProps) {
  const [files, setFiles] = useState<File[]>([]);
  const [videoPreviewUrl, setVideoPreviewUrl] = useState<string | null>(null);
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [editingQuestion, setEditingQuestion] = useState(false);
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
          const r = await createTask(files[0], undefined, undefined, question);
          onTaskCreated([r]);
        } else {
          const r = await createBatchTasks(files, question);
          if (r.tasks.length > 0) {
            onTaskCreated(r.tasks);
          }
        }
        setFiles([]);
      }
    } catch (e) {
      alert("创建任务失败: " + (e as Error).message);
    }
    setLoading(false);
  }, [files, question, onTaskCreated]);

  return (
    <div className="h-full flex flex-col justify-center items-center gap-6 max-w-4xl mx-auto w-full pb-10">
      <div className="text-center mb-6">
        <h2 className="text-3xl font-bold text-slate-900 tracking-tight flex items-center justify-center gap-3 mb-3">
          <Activity className="w-8 h-8 text-[#002FA7]" />
          材料拉伸智能分析
        </h2>
        <p className="text-sm text-slate-500">上传拉伸试验视频，自动推理并标记断裂区间。</p>
        <p className="tech-label mt-2">TENSILE FRACTURE ANALYSIS</p>
      </div>

      <div className="tech-panel tech-corners p-8 flex flex-col md:flex-row gap-8 w-full">
        {/* Left: Upload Controls */}
        <div className="flex-1 flex flex-col gap-5">
          <div className="flex flex-col gap-3">
            <button 
              onClick={handleUpload} 
              className="flex flex-col items-center justify-center gap-1.5 px-6 py-4 bg-white hover:bg-slate-50 border border-dashed border-slate-300 hover:border-[#002FA7]/60 hover:text-[#002FA7] text-slate-700 rounded-lg transition-all w-full"
            >
              <span className="flex items-center gap-2 text-base font-medium">
                <Upload className="w-5 h-5 text-[#002FA7]" /> 选择视频文件
              </span>
              <span className="tech-label">SELECT VIDEO FILE</span>
            </button>
            <input ref={fileRef} type="file" accept="video/*" className="hidden" onChange={handleFileChange} />
          </div>

          {files.length > 0 && (
            <div className="space-y-2 max-h-[120px] overflow-auto custom-scrollbar mt-2 bg-slate-50/50 p-3 rounded-lg border border-slate-200">
              {files.map((f, i) => (
                <div key={i} className="flex items-center gap-3 text-xs text-slate-700 bg-white border border-slate-200 px-3 py-2 rounded-md">
                  <FileVideo className="w-4 h-4 text-[#002FA7]" />
                  <span className="flex-1 truncate font-mono">{f.name}</span>
                  <button onClick={() => removeFile(i)} className="text-slate-400 hover:text-rose-500 transition-colors">
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            onClick={handleStart}
            disabled={loading || files.length === 0}
            className="mt-4 flex items-center justify-center gap-2 px-6 py-3.5 bg-[#002FA7] hover:bg-[#002FA7]/90 disabled:opacity-50 disabled:hover:bg-[#002FA7] text-white rounded-lg text-base font-semibold transition-all"
          >
            {loading ? (
              <><Activity className="w-5 h-5 animate-spin" /> 准备分析中...</>
            ) : (
              <><Play className="w-5 h-5 fill-current" /> 开始分析任务</>
            )}
          </button>

          {/* Question: background-style hint (click to edit) */}
          <div className="text-center">
            {editingQuestion ? (
              <input
                autoFocus
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onBlur={() => {
                  if (!question.trim()) setQuestion(DEFAULT_QUESTION);
                  setEditingQuestion(false);
                }}
                onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                className="w-full px-3 py-1.5 bg-white border border-slate-200 rounded-md font-mono text-xs text-slate-700 outline-none focus:border-[#002FA7]/40 focus:ring-1 focus:ring-[#002FA7]/15 transition-all"
              />
            ) : (
              <button
                type="button"
                onClick={() => setEditingQuestion(true)}
                className="group inline-flex items-center gap-1.5 text-[11px] text-slate-400 hover:text-slate-600 transition-colors"
                title="点击修改本次分析要回答的问题（不影响视觉推理）"
              >
                <span className="truncate max-w-[280px] font-mono">分析将回答：「{question}」</span>
                <Pencil className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
              </button>
            )}
          </div>
        </div>

        {/* Right: Video Preview */}
        <div className="flex-1 flex flex-col md:border-l border-t md:border-t-0 border-slate-200 md:pl-8 pt-6 md:pt-0">
          <h3 className="tech-label mb-3">预览</h3>
          {videoPreviewUrl ? (
            <div className="bg-slate-900 rounded-lg overflow-hidden border border-slate-200 flex-1 min-h-[220px] max-h-[300px] relative group">
              <span className="tech-label absolute top-2 right-2 z-10 bg-white/80 px-1.5 py-0.5 rounded">PREVIEW</span>
              <video src={videoPreviewUrl} controls className="w-full h-full object-contain" />
            </div>
          ) : (
            <div className="flex-1 bg-slate-50/50 rounded-lg border border-slate-200 border-dashed flex items-center justify-center flex-col gap-3 text-slate-400 min-h-[220px]">
              <FileVideo className="w-8 h-8 text-slate-300" strokeWidth={1.25} />
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
          <div className="mt-4 p-4 bg-slate-50 border border-slate-200 rounded-lg w-full max-w-md text-center">
            <p className="text-xs text-slate-500 mb-3">批量处理模式不提供实时的过程可视化跟踪，所有任务将在后台排队执行。</p>
            <input ref={batchFileRef} type="file" multiple accept="video/*" className="hidden" onChange={handleFileChange} />
            <button 
              onClick={handleBatchUpload}
              className="px-4 py-2 bg-white border border-slate-300 text-slate-700 hover:bg-slate-50 hover:border-[#002FA7]/50 text-sm font-medium rounded-md transition-colors"
            >
              选择多个文件
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
