import {AnimatePresence, motion} from 'framer-motion';
import {AlertCircle, CheckCircle, XCircle, Loader2} from 'lucide-react';

export interface QuestionApprovalDialogProps {
  open: boolean;
  /** 待审批的题目信息（来自 pending_approval 字段） */
  approvalData: Record<string, unknown> | null;
  /** 审批中 */
  loading: boolean;
  /** 审批通过 */
  onApprove: () => void;
  /** 审批驳回 */
  onReject: () => void;
  /** 关闭对话框（不做任何操作） */
  onClose: () => void;
}

export default function QuestionApprovalDialog({
  open,
  approvalData,
  loading,
  onApprove,
  onReject,
  onClose,
}: QuestionApprovalDialogProps) {
  if (!open) return null;

  const question = approvalData?.question as string | undefined;
  const category = approvalData?.category as string | undefined;
  const prompt = (approvalData?.prompt as string | undefined) || '这道题是否合适？';

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* 背景遮罩 */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50"
          />

          {/* 对话框 */}
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 20 }}
              onClick={(e) => e.stopPropagation()}
              className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl max-w-lg w-full p-6"
            >
              {/* 标题 */}
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 bg-amber-100 dark:bg-amber-900/30 rounded-lg">
                  <AlertCircle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
                </div>
                <h3 className="text-xl font-bold text-slate-900 dark:text-white">
                  题目审批
                </h3>
              </div>

              {/* 提示文字 */}
              <p className="text-slate-600 dark:text-slate-300 mb-4 text-sm">
                {prompt}
              </p>

              {/* 题目卡片 */}
              {question && (
                <div className="bg-slate-50 dark:bg-slate-700/50 rounded-xl p-4 mb-6 border border-slate-200 dark:border-slate-600">
                  {category && (
                    <span className="inline-block px-2.5 py-1 bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-300 text-xs font-medium rounded-full mb-3">
                      {category}
                    </span>
                  )}
                  <p className="text-slate-800 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">
                    {question}
                  </p>
                </div>
              )}

              {/* 按钮 */}
              <div className="flex gap-3 justify-end">
                <motion.button
                  onClick={onReject}
                  disabled={loading}
                  className="px-5 py-2.5 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 rounded-xl font-medium hover:bg-red-50 dark:hover:bg-red-900/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <XCircle className="w-4 h-4" />
                  )}
                  驳回
                </motion.button>
                <motion.button
                  onClick={onApprove}
                  disabled={loading}
                  className="px-5 py-2.5 bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-600 hover:to-primary-700 text-white rounded-xl font-semibold shadow-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <CheckCircle className="w-4 h-4" />
                  )}
                  通过
                </motion.button>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}