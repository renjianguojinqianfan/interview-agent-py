import {Fragment, useCallback, useEffect, useRef, useState} from 'react';
import {usePolling} from '../hooks/usePolling';
import {AnimatePresence, motion} from 'framer-motion';
import {
  AlertCircle,
  Check,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Database,
  Download,
  Edit3,
  Eye,
  FilePlus2,
  FileText,
  HardDrive,
  Loader2,
  MessageSquare,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
  XCircle,
} from 'lucide-react';
import {
  knowledgeBaseApi,
  KnowledgeBaseDocumentItem,
  KnowledgeBaseItem,
  KnowledgeBaseStats,
  SortOption,
  VectorStatus,
} from '../api/knowledgebase';
import DeleteConfirmDialog from '../components/DeleteConfirmDialog';

interface KnowledgeBaseManagePageProps {
  onUpload: () => void;
  onChat: () => void;
}

// 格式化文件大小
function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// 格式化日期
function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// 状态图标组件
function StatusIcon({ status }: { status: VectorStatus }) {
  switch (status) {
    case 'COMPLETED':
      return <CheckCircle className="w-4 h-4 text-green-500" />;
    case 'PROCESSING':
      return <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />;
    case 'PENDING':
      return <Clock className="w-4 h-4 text-yellow-500" />;
    case 'FAILED':
      return <AlertCircle className="w-4 h-4 text-red-500" />;
    default:
      return <CheckCircle className="w-4 h-4 text-green-500" />;
  }
}

// 状态文本
function getStatusText(status: VectorStatus): string {
  switch (status) {
    case 'COMPLETED':
      return '已完成';
    case 'PROCESSING':
      return '处理中';
    case 'PENDING':
      return '待处理';
    case 'FAILED':
      return '失败';
    default:
      return '未知';
  }
}

// 统计卡片组件
function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: number;
  color: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white dark:bg-slate-800 rounded-xl p-6 shadow-sm border border-slate-100 dark:border-slate-700"
    >
      <div className="flex items-center gap-4">
        <div className={`p-3 rounded-lg ${color}`}>
          <Icon className="w-6 h-6 text-white" />
        </div>
        <div>
            <p className="text-sm text-slate-500 dark:text-slate-400">{label}</p>
            <p className="text-2xl font-bold text-slate-800 dark:text-white">{value.toLocaleString()}</p>
        </div>
      </div>
    </motion.div>
  );
}

export default function KnowledgeBaseManagePage({ onUpload, onChat }: KnowledgeBaseManagePageProps) {
  const [stats, setStats] = useState<KnowledgeBaseStats | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchKeyword, setSearchKeyword] = useState('');
  const [sortBy, setSortBy] = useState<SortOption>('time');
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [deleteItem, setDeleteItem] = useState<KnowledgeBaseItem | null>(null);
  const [deleting, setDeleting] = useState(false);

  // 分类编辑状态
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editingCategoryValue, setEditingCategoryValue] = useState('');
  const [savingCategory, setSavingCategory] = useState(false);
  const categoryInputRef = useRef<HTMLInputElement>(null);

  // 重新向量化状态
  const [revectorizing, setRevectorizing] = useState<number | null>(null);

  // 多文档面板状态（ADR-0018）
  const [expandedKbId, setExpandedKbId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<KnowledgeBaseDocumentItem[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [addingDocument, setAddingDocument] = useState(false);
  const [deletingDocumentId, setDeletingDocumentId] = useState<number | null>(null);
  const [deleteDocumentItem, setDeleteDocumentItem] = useState<KnowledgeBaseDocumentItem | null>(null);
  const docFileInputRef = useRef<HTMLInputElement>(null);

  // Toast 通知（复用 SettingsPage 模式）
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const showToast = useCallback((message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  // 加载数据（不显示loading状态，用于轮询）
  const loadDataSilent = useCallback(async () => {
    const [statsData, kbList, categoryList] = await Promise.all([
      knowledgeBaseApi.getStatistics(),
      searchKeyword
        ? knowledgeBaseApi.search(searchKeyword)
        : selectedCategory
        ? knowledgeBaseApi.getByCategory(selectedCategory)
        : knowledgeBaseApi.getAllKnowledgeBases(sortBy),
      knowledgeBaseApi.getAllCategories(),
    ]);
    setStats(statsData);
    setKnowledgeBases(kbList);
    setCategories(categoryList);
  }, [searchKeyword, sortBy, selectedCategory]);

  // 加载数据
  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [statsData, kbList, categoryList] = await Promise.all([
        knowledgeBaseApi.getStatistics(),
        searchKeyword
          ? knowledgeBaseApi.search(searchKeyword)
          : selectedCategory
          ? knowledgeBaseApi.getByCategory(selectedCategory)
          : knowledgeBaseApi.getAllKnowledgeBases(sortBy),
        knowledgeBaseApi.getAllCategories(),
      ]);
      setStats(statsData);
      setKnowledgeBases(kbList);
      setCategories(categoryList);
    } catch (error) {
      console.error('加载数据失败:', error);
    } finally {
      setLoading(false);
    }
  }, [searchKeyword, sortBy, selectedCategory]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 轮询：当有 PENDING 或 PROCESSING 状态时，每5秒刷新一次（指数退避）
  const hasPendingItems = knowledgeBases.some(
    kb => kb.vectorStatus === 'PENDING' || kb.vectorStatus === 'PROCESSING'
  );
  usePolling({
    callback: loadDataSilent,
    interval: 5000,
    enabled: hasPendingItems && !loading,
  });

  // 多文档面板（ADR-0018）：静默刷新（不触发 loading 态，用于轮询）
  const loadDocumentsSilent = useCallback(async (kbId: number) => {
    setDocuments(await knowledgeBaseApi.listDocuments(kbId));
  }, []);

  // 轮询文档列表：面板展开且有非终态文档时，每 5 秒刷新（指数退避）
  const hasNonTerminalDocs = expandedKbId !== null && documents.some(
    doc => doc.vectorStatus === 'PENDING' || doc.vectorStatus === 'PROCESSING'
  );
  const pollDocuments = useCallback(() => {
    if (expandedKbId !== null) loadDocumentsSilent(expandedKbId);
  }, [expandedKbId, loadDocumentsSilent]);
  usePolling({
    callback: pollDocuments,
    interval: 5000,
    enabled: hasNonTerminalDocs,
  });

  // 重新向量化
  const handleRevectorize = async (id: number) => {
    try {
      setRevectorizing(id);
      await knowledgeBaseApi.revectorize(id);
      await loadDataSilent();
    } catch (error) {
      console.error('重新向量化失败:', error);
    } finally {
      setRevectorizing(null);
    }
  };

  // 删除知识库
  const handleDelete = async () => {
    if (!deleteItem) return;
    try {
      setDeleting(true);
      await knowledgeBaseApi.deleteKnowledgeBase(deleteItem.id);
      setDeleteItem(null);
      await loadData();
    } catch (error) {
      console.error('删除失败:', error);
    } finally {
      setDeleting(false);
    }
  };

  // 下载知识库
    const handleDownload = async (kb: KnowledgeBaseItem) => {
        try {
            const blob = await knowledgeBaseApi.downloadKnowledgeBase(kb.id);
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = kb.originalFilename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            window.URL.revokeObjectURL(url);
        } catch (error) {
            console.error('下载失败:', error);
        }
  };

  // 开始编辑分类
  const handleStartEditCategory = (kb: KnowledgeBaseItem) => {
    setEditingCategoryId(kb.id);
    setEditingCategoryValue(kb.category || '');
    setTimeout(() => {
      categoryInputRef.current?.focus();
    }, 50);
  };

  // 取消编辑分类
  const handleCancelEditCategory = () => {
    setEditingCategoryId(null);
    setEditingCategoryValue('');
  };

  // 保存分类
  const handleSaveCategory = async (id: number) => {
    try {
      setSavingCategory(true);
      const categoryToSave = editingCategoryValue.trim() || null;
      await knowledgeBaseApi.updateCategory(id, categoryToSave);
      setEditingCategoryId(null);
      setEditingCategoryValue('');
      await loadData();
    } catch (error) {
      console.error('更新分类失败:', error);
    } finally {
      setSavingCategory(false);
    }
  };

  // 处理分类输入框按键
  const handleCategoryKeyDown = (e: React.KeyboardEvent, id: number) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSaveCategory(id);
    } else if (e.key === 'Escape') {
      handleCancelEditCategory();
    }
  };

  // 搜索处理
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadData();
  };

  // —— 多文档面板（ADR-0018） ——
  const loadDocuments = useCallback(async (kbId: number) => {
    try {
      setDocsLoading(true);
      setDocuments(await knowledgeBaseApi.listDocuments(kbId));
    } catch (error) {
      console.error('加载文档列表失败:', error);
    } finally {
      setDocsLoading(false);
    }
  }, []);

  const handleToggleDocuments = (kbId: number) => {
    if (expandedKbId === kbId) {
      setExpandedKbId(null);
      setDocuments([]);
      return;
    }
    setExpandedKbId(kbId);
    loadDocuments(kbId);
  };

  const handleAddDocument = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file || expandedKbId === null) return;
    try {
      setAddingDocument(true);
      await knowledgeBaseApi.addDocument(expandedKbId, file);
      await loadDocuments(expandedKbId);
      await loadDataSilent();
    } catch (error) {
      console.error('追加文档失败:', error);
      showToast(error instanceof Error ? error.message : '追加文档失败', 'error');
    } finally {
      setAddingDocument(false);
    }
  };

  const handleDeleteDocument = async (documentId: number) => {
    if (expandedKbId === null) return;
    try {
      setDeletingDocumentId(documentId);
      await knowledgeBaseApi.deleteDocument(expandedKbId, documentId);
      setDeleteDocumentItem(null);
      await loadDocuments(expandedKbId);
      await loadDataSilent();
    } catch (error) {
      console.error('删除文档失败:', error);
    } finally {
      setDeletingDocumentId(null);
    }
  };

  return (
    <div className="max-w-7xl mx-auto">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-8">
        <div>
            <h1 className="text-2xl font-bold text-slate-800 dark:text-white flex items-center gap-3">
            <Database className="w-7 h-7 text-primary-500" />
            知识库管理
          </h1>
            <p className="text-slate-500 dark:text-slate-400 mt-1">管理您的知识库文件，查看使用统计</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={onUpload}
            className="flex items-center gap-2 px-4 py-2 bg-primary-500 text-white rounded-lg hover:bg-primary-600 transition-colors"
          >
            <Upload className="w-4 h-4" />
            上传知识库
          </button>
          <button
            onClick={onChat}
            className="flex items-center gap-2 px-4 py-2 bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-600 transition-colors"
          >
            <MessageSquare className="w-4 h-4" />
            问答助手
          </button>
        </div>
      </div>
      {/* 统计卡片 */}
      {stats && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <StatCard
            icon={Database}
            label="知识库总数"
            value={stats.totalCount}
            color="bg-primary-500"
          />
          <StatCard
            icon={MessageSquare}
            label="总提问次数"
            value={stats.totalQuestionCount}
            color="bg-indigo-500"
          />
          <StatCard
            icon={Eye}
            label="总访问次数"
            value={stats.totalAccessCount}
            color="bg-emerald-500"
          />
        </div>
      )}

      {/* 搜索和筛选栏 */}
        <div
            className="bg-white dark:bg-slate-800 rounded-xl p-4 shadow-sm border border-slate-100 dark:border-slate-700 mb-6">
        <div className="flex flex-wrap items-center gap-4">
          {/* 搜索框 */}
          <form onSubmit={handleSearch} className="flex-1 min-w-[200px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="text"
                value={searchKeyword}
                onChange={(e) => setSearchKeyword(e.target.value)}
                placeholder="搜索知识库名称..."
                className="w-full pl-10 pr-4 py-2 border border-slate-200 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent bg-white dark:bg-slate-700 text-slate-900 dark:text-white"
              />
            </div>
          </form>

          {/* 排序选择 */}
          <div className="relative">
            <select
              value={sortBy}
              onChange={(e) => {
                setSortBy(e.target.value as SortOption);
                setSearchKeyword('');
                setSelectedCategory(null);
              }}
              className="appearance-none pl-4 pr-10 py-2 border border-slate-200 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white dark:bg-slate-700 text-slate-900 dark:text-white cursor-pointer"
            >
              <option value="time">按时间排序</option>
              <option value="size">按大小排序</option>
              <option value="access">按访问排序</option>
              <option value="question">按提问排序</option>
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          </div>

          {/* 分类筛选 */}
          <div className="relative">
            <select
              value={selectedCategory || ''}
              onChange={(e) => {
                setSelectedCategory(e.target.value || null);
                setSearchKeyword('');
              }}
              className="appearance-none pl-4 pr-10 py-2 border border-slate-200 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white dark:bg-slate-700 text-slate-900 dark:text-white cursor-pointer"
            >
              <option value="">全部分类</option>
              {categories.map((cat) => (
                <option key={cat} value={cat}>
                  {cat}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          </div>
        </div>
      </div>

      {/* 知识库列表 */}
        <div
            className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="w-8 h-8 text-primary-500 animate-spin" />
          </div>
        ) : knowledgeBases.length === 0 ? (
          <div className="text-center py-20">
            <HardDrive className="w-16 h-16 text-slate-300 mx-auto mb-4" />
              <p className="text-slate-500 dark:text-slate-400">暂无知识库</p>
            <button
              onClick={onUpload}
              className="mt-4 text-primary-500 hover:text-primary-600"
            >
              上传第一个知识库
            </button>
          </div>
        ) : (
          <table className="w-full">
              <thead className="bg-slate-50 dark:bg-slate-700 border-b border-slate-100 dark:border-slate-600">
              <tr>
                  <th className="text-left px-6 py-4 text-sm font-medium text-slate-600 dark:text-slate-300">
                  名称
                </th>
                  <th className="text-left px-6 py-4 text-sm font-medium text-slate-600 dark:text-slate-300">
                  分类
                </th>
                  <th className="text-left px-6 py-4 text-sm font-medium text-slate-600 dark:text-slate-300">
                  大小
                </th>
                  <th className="text-left px-6 py-4 text-sm font-medium text-slate-600 dark:text-slate-300">
                  状态
                </th>
                  <th className="text-left px-6 py-4 text-sm font-medium text-slate-600 dark:text-slate-300">
                  提问
                </th>
                  <th className="text-left px-6 py-4 text-sm font-medium text-slate-600 dark:text-slate-300">
                  上传时间
                </th>
                  <th className="text-right px-6 py-4 text-sm font-medium text-slate-600 dark:text-slate-300">
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              {knowledgeBases.map((kb, index) => (
                <Fragment key={kb.id}>
                <motion.tr
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className="border-b border-slate-50 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <FileText className="w-5 h-5 text-slate-400" />
                      <div>
                          <p className="font-medium text-slate-800 dark:text-white">{kb.name}</p>
                          <p className="text-xs text-slate-400 dark:text-slate-500">{kb.originalFilename}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <AnimatePresence mode="wait">
                      {editingCategoryId === kb.id ? (
                        <motion.div
                          key="editing"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          className="flex items-center gap-2"
                        >
                          <input
                            ref={categoryInputRef}
                            type="text"
                            value={editingCategoryValue}
                            onChange={(e) => setEditingCategoryValue(e.target.value)}
                            onKeyDown={(e) => handleCategoryKeyDown(e, kb.id)}
                            placeholder="输入分类名称"
                            list="category-suggestions"
                            className="w-24 px-2 py-1 text-sm border border-primary-300 dark:border-primary-600 rounded focus:outline-none focus:ring-2 focus:ring-primary-500 bg-white dark:bg-slate-700 text-slate-900 dark:text-white"
                            disabled={savingCategory}
                          />
                          <datalist id="category-suggestions">
                            {categories.map((cat) => (
                              <option key={cat} value={cat} />
                            ))}
                          </datalist>
                          <button
                            onClick={() => handleSaveCategory(kb.id)}
                            disabled={savingCategory}
                            className="p-1 text-green-600 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-900/20 rounded transition-colors disabled:opacity-50"
                            title="保存"
                          >
                            {savingCategory ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <Check className="w-4 h-4" />
                            )}
                          </button>
                          <button
                            onClick={handleCancelEditCategory}
                            disabled={savingCategory}
                            className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-600 rounded transition-colors disabled:opacity-50"
                            title="取消"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </motion.div>
                      ) : (
                        <motion.div
                          key="display"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          className="flex items-center gap-2 group/category"
                        >
                          {kb.category ? (
                              <span
                                  className="px-2 py-1 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded text-sm">
                              {kb.category}
                            </span>
                          ) : (
                              <span className="text-slate-400 dark:text-slate-500 text-sm">未分类</span>
                          )}
                          <button
                            onClick={() => handleStartEditCategory(kb)}
                            className="p-1 text-slate-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/30 rounded opacity-0 group-hover/category:opacity-100 transition-all"
                            title="编辑分类"
                          >
                            <Edit3 className="w-3.5 h-3.5" />
                          </button>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </td>
                    <td className="px-6 py-4 text-sm text-slate-600 dark:text-slate-300">
                    {formatFileSize(kb.fileSize)}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <StatusIcon status={kb.vectorStatus} />
                        <span className="text-sm text-slate-600 dark:text-slate-300">
                        {getStatusText(kb.vectorStatus)}
                      </span>
                    </div>
                  </td>
                    <td className="px-6 py-4 text-sm text-slate-600 dark:text-slate-300">
                    {kb.questionCount}
                  </td>
                    <td className="px-6 py-4 text-sm text-slate-500 dark:text-slate-400">
                    {formatDate(kb.uploadedAt)}
                  </td>
                  <td className="px-6 py-4 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {/* 文档列表展开按钮（ADR-0018 一库多文档） */}
                      <button
                        onClick={() => handleToggleDocuments(kb.id)}
                        className="p-2 text-slate-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/30 rounded-lg transition-colors"
                        title="文档列表"
                      >
                        {expandedKbId === kb.id ? (
                          <ChevronUp className="w-4 h-4" />
                        ) : (
                          <ChevronDown className="w-4 h-4" />
                        )}
                      </button>
                      {/* 下载按钮 */}
                      <button
                        onClick={() => handleDownload(kb)}
                        className="p-2 text-slate-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/30 rounded-lg transition-colors"
                        title="下载"
                      >
                        <Download className="w-4 h-4" />
                      </button>
                      {/* 重新向量化按钮（仅 FAILED 状态显示） */}
                      {kb.vectorStatus === 'FAILED' && (
                        <button
                          onClick={() => handleRevectorize(kb.id)}
                          disabled={revectorizing === kb.id}
                          className="p-2 text-slate-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/30 rounded-lg transition-colors disabled:opacity-50"
                          title="重新向量化"
                        >
                          <RefreshCw className={`w-4 h-4 ${revectorizing === kb.id ? 'animate-spin' : ''}`} />
                        </button>
                      )}
                      {/* 删除按钮 */}
                      <button
                        onClick={() => setDeleteItem(kb)}
                        className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded-lg transition-colors"
                        title="删除"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </motion.tr>
                {/* 文档面板（ADR-0018）：列表 + 追加 + 删除 */}
                {expandedKbId === kb.id && (
                  <tr className="border-b border-slate-50 dark:border-slate-700 bg-slate-50/60 dark:bg-slate-700/30">
                    <td colSpan={7} className="px-6 py-4">
                      <div className="flex items-center justify-between mb-3">
                        <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
                          文档列表（{documents.length}）
                        </p>
                        <button
                          onClick={() => docFileInputRef.current?.click()}
                          disabled={addingDocument}
                          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-900/30 rounded-lg transition-colors disabled:opacity-50"
                        >
                          {addingDocument ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <FilePlus2 className="w-4 h-4" />
                          )}
                          追加文件
                        </button>
                      </div>
                      {docsLoading ? (
                        <div className="flex items-center justify-center py-4">
                          <Loader2 className="w-5 h-5 text-primary-500 animate-spin" />
                        </div>
                      ) : documents.length === 0 ? (
                        <p className="text-sm text-slate-400 dark:text-slate-500 py-2">暂无文档</p>
                      ) : (
                        <div className="space-y-2">
                          {documents.map((doc) => (
                            <div
                              key={doc.id}
                              className="flex items-center justify-between px-3 py-2 bg-white dark:bg-slate-800 rounded-lg border border-slate-100 dark:border-slate-700"
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                <FileText className="w-4 h-4 text-slate-400 shrink-0" />
                                <span className="text-sm text-slate-700 dark:text-slate-200 truncate">
                                  {doc.originalFilename}
                                </span>
                                <span className="text-xs text-slate-400 dark:text-slate-500 shrink-0">
                                  {formatFileSize(doc.fileSize ?? 0)}
                                </span>
                              </div>
                              <div className="flex items-center gap-2 shrink-0">
                                <StatusIcon status={doc.vectorStatus} />
                                <span className="text-xs text-slate-500 dark:text-slate-400">
                                  {getStatusText(doc.vectorStatus)}
                                </span>
                                <button
                                  onClick={() => setDeleteDocumentItem(doc)}
                                  disabled={deletingDocumentId === doc.id}
                                  className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded transition-colors disabled:opacity-50"
                                  title="删除文档"
                                >
                                  {deletingDocumentId === doc.id ? (
                                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  ) : (
                                    <Trash2 className="w-3.5 h-3.5" />
                                  )}
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 追加文档的隐藏文件选择器（ADR-0018） */}
      <input
        ref={docFileInputRef}
        type="file"
        accept=".txt,.md,.pdf,.docx"
        className="hidden"
        onChange={handleAddDocument}
      />

      {/* 删除知识库确认对话框 */}
      <DeleteConfirmDialog
        open={deleteItem !== null}
        item={deleteItem}
        itemType="知识库"
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setDeleteItem(null)}
      />

      {/* 删除文档确认对话框 */}
      <DeleteConfirmDialog
        open={deleteDocumentItem !== null}
        item={deleteDocumentItem ? { ...deleteDocumentItem, filename: deleteDocumentItem.originalFilename } : null}
        itemType="文档"
        loading={deletingDocumentId !== null}
        onConfirm={() => deleteDocumentItem && handleDeleteDocument(deleteDocumentItem.id)}
        onCancel={() => setDeleteDocumentItem(null)}
      />

      {/* Toast 通知 */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: 50, x: '-50%' }}
            animate={{ opacity: 1, y: 0, x: '-50%' }}
            exit={{ opacity: 0, y: 50, x: '-50%' }}
            className={`fixed bottom-6 left-1/2 px-5 py-3 rounded-xl shadow-lg text-sm font-medium
              flex items-center gap-2 z-[60] ${
                toast.type === 'success'
                  ? 'bg-emerald-600 text-white'
                  : 'bg-red-600 text-white'
              }`}
          >
            {toast.type === 'success'
              ? <CheckCircle className="w-4 h-4" />
              : <XCircle className="w-4 h-4" />
            }
            {toast.message}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
