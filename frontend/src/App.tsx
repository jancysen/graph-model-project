import React, { useState, useEffect, useRef, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { Send, Loader2, AlertCircle, Database, GitBranch, MessageSquare, ChevronRight, X } from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────
interface GraphNode {
  id: string
  label: string
  type: string
  properties: Record<string, string>
  x?: number
  y?: number
}

interface GraphEdge {
  source: string
  target: string
  label: string
}

interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

interface Message {
  role: 'user' | 'assistant'
  content: string
  sql?: string
  data?: { columns: string[]; rows: Record<string, string>[] }
  off_topic?: boolean
  loading?: boolean
  highlighted_node_ids?: string[]
}

// ── Constants ─────────────────────────────────────────────────────────────────
const NODE_COLORS: Record<string, string> = {
  SalesOrder: '#6366f1',
  Customer: '#10b981',
  Delivery: '#f59e0b',
  BillingDoc: '#ef4444',
  Payment: '#3b82f6',
  JournalEntry: '#8b5cf6',
}

const NODE_SIZES: Record<string, number> = {
  SalesOrder: 7,
  Customer: 9,
  Delivery: 6,
  BillingDoc: 6,
  Payment: 5,
  JournalEntry: 4,
}

const SAMPLE_QUESTIONS = [
  'Which products are associated with the highest number of billing documents?',
  'Trace the full flow of billing document 90504248',
  'Which sales orders have been delivered but not billed?',
  'Show me the top 5 customers by total order amount',
  'Which billing documents have been cancelled?',
  'What is the total payment amount received by customer?',
]

const API_BASE = import.meta.env.VITE_API_URL || ''

// ── Components ────────────────────────────────────────────────────────────────
function NodePanel({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  const color = NODE_COLORS[node.type] || '#94a3b8'
  return (
    <div className="absolute top-4 left-4 z-10 bg-gray-900 border border-gray-700 rounded-xl p-4 w-64 shadow-2xl">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ background: color + '33', color }}>
          {node.type}
        </span>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-300 transition-colors">
          <X size={14} />
        </button>
      </div>
      <div className="text-white font-semibold text-sm mb-3">{node.label}</div>
      <div className="space-y-1.5">
        {Object.entries(node.properties).filter(([, v]) => v).map(([k, v]) => (
          <div key={k} className="flex flex-col">
            <span className="text-gray-500 text-xs uppercase tracking-wider">{k}</span>
            <span className="text-gray-200 text-xs font-mono truncate">{String(v)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function DataTable({ columns, rows }: { columns: string[]; rows: Record<string, string>[] }) {
  if (!rows.length) return <p className="text-gray-400 text-sm">No results found.</p>
  return (
    <div className="overflow-x-auto mt-3 rounded-lg border border-gray-700">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-gray-800">
            {columns.map(c => (
              <th key={c} className="px-3 py-2 text-left text-gray-400 font-medium whitespace-nowrap">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 20).map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? 'bg-gray-900' : 'bg-gray-850'}>
              {columns.map(c => (
                <td key={c} className="px-3 py-1.5 text-gray-300 whitespace-nowrap font-mono">{String(row[c] ?? '')}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 20 && (
        <div className="px-3 py-2 text-gray-500 text-xs bg-gray-800 rounded-b-lg">
          Showing 20 of {rows.length} rows
        </div>
      )}
    </div>
  )
}

function MessageBubble({ msg }: { msg: Message }) {
  const [showSql, setShowSql] = useState(false)
  const [showTable, setShowTable] = useState(false)

  if (msg.role === 'user') {
    return (
      <div className="flex justify-end">
        <div className="bg-indigo-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 max-w-xs text-sm">
          {msg.content}
        </div>
      </div>
    )
  }

  return (
    <div className="flex gap-2.5">
      <div className="w-7 h-7 rounded-full bg-gray-700 flex items-center justify-center flex-shrink-0 mt-0.5">
        <Database size={14} className="text-indigo-400" />
      </div>
      <div className="flex-1 min-w-0">
        {msg.loading ? (
          <div className="flex items-center gap-2 text-gray-400 text-sm py-1">
            <Loader2 size={14} className="animate-spin" />
            Querying dataset…
          </div>
        ) : (
          <>
            <div className={`text-sm leading-relaxed ${msg.off_topic ? 'text-amber-400' : 'text-gray-200'}`}>
              {msg.off_topic && <AlertCircle size={14} className="inline mr-1.5 mb-0.5" />}
              {msg.content}
            </div>
            {msg.sql && (
              <div className="mt-2 space-y-1">
                <button
                  onClick={() => setShowSql(s => !s)}
                  className="flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
                >
                  <ChevronRight size={12} className={`transition-transform ${showSql ? 'rotate-90' : ''}`} />
                  {showSql ? 'Hide' : 'View'} SQL
                </button>
                {showSql && (
                  <pre className="bg-gray-900 border border-gray-700 rounded-lg p-3 text-xs text-green-400 overflow-x-auto whitespace-pre-wrap">
                    {msg.sql}
                  </pre>
                )}
              </div>
            )}
            {msg.data && msg.data.rows.length > 0 && (
              <div className="mt-2">
                <button
                  onClick={() => setShowTable(s => !s)}
                  className="flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
                >
                  <ChevronRight size={12} className={`transition-transform ${showTable ? 'rotate-90' : ''}`} />
                  {showTable ? 'Hide' : 'Show'} data ({msg.data.rows.length} rows)
                </button>
                {showTable && <DataTable columns={msg.data.columns} rows={msg.data.rows} />}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── Legend ────────────────────────────────────────────────────────────────────
function Legend() {
  return (
    <div className="absolute bottom-4 left-4 z-10 bg-gray-900/90 border border-gray-700 rounded-xl p-3">
      <div className="text-gray-400 text-xs font-semibold uppercase tracking-wider mb-2">Node types</div>
      <div className="space-y-1.5">
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-2">
            <div className="w-3 h-3 rounded-full" style={{ background: color }} />
            <span className="text-gray-300 text-xs">{type}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────────────────
export default function App() {
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; links: GraphEdge[] }>({ nodes: [], links: [] })
  const [loading, setLoading] = useState(true)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: 'Hello! I can answer questions about your SAP Order-to-Cash data — orders, deliveries, billing documents, payments, products, and customers. Try one of the sample questions or ask your own.',
    }
  ])
  const [input, setInput] = useState('')
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set())
  const [querying, setQuerying] = useState(false)
  const [activeTab, setActiveTab] = useState<'graph' | 'chat'>('graph')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const graphRef = useRef<any>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/graph`)
      .then(r => r.json())
      .then((d: GraphData) => {
        setGraphData({ nodes: d.nodes, links: d.edges })
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendQuery = useCallback(async (question: string) => {
    if (!question.trim() || querying) return
    setInput('')
    setQuerying(true)
    setHighlightedNodes(new Set())   // clear previous highlights
    setActiveTab('chat')

    const userMsg: Message = { role: 'user', content: question }
    const loadingMsg: Message = { role: 'assistant', content: '', loading: true }
    setMessages(prev => [...prev, userMsg, loadingMsg])

    try {
      const res = await fetch(`${API_BASE}/api/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      const data = await res.json()
      const ids: string[] = data.highlighted_node_ids || []
      setMessages(prev => [
        ...prev.slice(0, -1),
        {
          role: 'assistant',
          content: data.answer,
          sql: data.sql,
          data: data.data,
          off_topic: data.off_topic,
          highlighted_node_ids: ids,
        }
      ])
      if (ids.length > 0) {
        setHighlightedNodes(new Set(ids))
        // Give the user a moment to read the answer then show the graph
        setTimeout(() => setActiveTab('graph'), 800)
      }
    } catch {
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: 'assistant', content: 'Error connecting to the backend. Please check the server is running.' }
      ])
    } finally {
      setQuerying(false)
    }
  }, [querying])

  const nodeColor = useCallback((node: any) => NODE_COLORS[node.type] || '#94a3b8', [])
  const nodeVal = useCallback((node: any) => NODE_SIZES[node.type] || 5, [])

  const nodeCanvasObject = useCallback((node: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const color = NODE_COLORS[node.type] || '#94a3b8'
    const size = (NODE_SIZES[node.type] || 5)
    const isHighlighted = highlightedNodes.size === 0 || highlightedNodes.has(node.id)
    const alpha = highlightedNodes.size === 0 ? 1 : (isHighlighted ? 1 : 0.12)

    ctx.globalAlpha = alpha

    // Glow ring for highlighted nodes
    if (isHighlighted && highlightedNodes.size > 0) {
      ctx.beginPath()
      ctx.arc(node.x, node.y, size + 4, 0, 2 * Math.PI)
      ctx.fillStyle = color + '40'   // 25% opacity halo
      ctx.fill()
      ctx.beginPath()
      ctx.arc(node.x, node.y, size + 2, 0, 2 * Math.PI)
      ctx.strokeStyle = color
      ctx.lineWidth = 1.5
      ctx.stroke()
    }

    // Main node circle
    ctx.beginPath()
    ctx.arc(node.x, node.y, size, 0, 2 * Math.PI)
    ctx.fillStyle = color
    ctx.fill()
    ctx.strokeStyle = 'rgba(255,255,255,0.15)'
    ctx.lineWidth = 0.5
    ctx.stroke()

    if (globalScale > 1.2 || (isHighlighted && highlightedNodes.size > 0 && globalScale > 0.7)) {
      ctx.font = `${Math.max(2, 4 / globalScale)}px sans-serif`
      ctx.fillStyle = isHighlighted ? 'rgba(255,255,255,0.95)' : 'rgba(255,255,255,0.8)'
      ctx.textAlign = 'center'
      ctx.fillText(node.label, node.x, node.y + size + 3)
    }

    ctx.globalAlpha = 1
  }, [highlightedNodes])

  return (
    <div className="flex flex-col h-screen bg-gray-950">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 bg-gray-900 border-b border-gray-800 flex-shrink-0">
        <div className="flex items-center gap-3">
          <GitBranch size={20} className="text-indigo-400" />
          <span className="font-semibold text-white">O2C Graph Explorer</span>
          <span className="text-xs text-gray-500 hidden sm:inline">SAP Order-to-Cash</span>
          {highlightedNodes.size > 0 && (
            <button
              onClick={() => { setHighlightedNodes(new Set()); setActiveTab('graph') }}
              className="flex items-center gap-1.5 text-xs bg-indigo-900/60 border border-indigo-600 text-indigo-300 hover:bg-indigo-800/70 rounded-full px-2.5 py-0.5 transition-colors"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
              {highlightedNodes.size} highlighted &nbsp;·&nbsp; Clear
            </button>
          )}
        </div>
        {/* Mobile tabs */}
        <div className="flex sm:hidden gap-1 bg-gray-800 rounded-lg p-0.5">
          {(['graph', 'chat'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1 rounded-md text-xs font-medium transition-colors capitalize ${
                activeTab === tab ? 'bg-indigo-600 text-white' : 'text-gray-400'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
        <div className="text-xs text-gray-600 hidden sm:block">
          {graphData.nodes.length} nodes · {graphData.links.length} edges
        </div>
      </header>

      {/* Main layout */}
      <div className="flex flex-1 min-h-0">
        {/* Graph panel */}
        <div className={`relative flex-1 ${activeTab !== 'graph' ? 'hidden sm:flex' : 'flex'} flex-col`}>
          {loading ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="flex flex-col items-center gap-3 text-gray-400">
                <Loader2 size={32} className="animate-spin text-indigo-400" />
                <span className="text-sm">Building graph from dataset…</span>
              </div>
            </div>
          ) : (
            <>
              <ForceGraph2D
                ref={graphRef}
                graphData={graphData}
                nodeId="id"
                nodeLabel={(n: any) => `${n.type}: ${n.label}`}
                nodeColor={nodeColor}
                nodeVal={nodeVal}
                nodeCanvasObject={nodeCanvasObject}
                nodeCanvasObjectMode={() => 'replace'}
                linkColor={() => 'rgba(148,163,184,0.25)'}
                linkWidth={0.8}
                linkDirectionalArrowLength={3}
                linkDirectionalArrowRelPos={1}
                linkLabel={(l: any) => l.label}
                backgroundColor="#0f1117"
                onNodeClick={(node: any) => setSelectedNode(node as GraphNode)}
                d3AlphaDecay={0.02}
                d3VelocityDecay={0.3}
              />
              {selectedNode && (
                <NodePanel node={selectedNode} onClose={() => setSelectedNode(null)} />
              )}
              <Legend />
            </>
          )}
        </div>

        {/* Divider */}
        <div className="hidden sm:block w-px bg-gray-800" />

        {/* Chat panel */}
        <div className={`w-full sm:w-96 flex flex-col bg-gray-900 ${activeTab !== 'chat' ? 'hidden sm:flex' : 'flex'}`}>
          {/* Sample questions */}
          <div className="px-4 pt-3 pb-2 border-b border-gray-800">
            <div className="flex items-center gap-1.5 mb-2">
              <MessageSquare size={13} className="text-gray-500" />
              <span className="text-xs text-gray-500 font-medium">Sample questions</span>
            </div>
            <div className="flex flex-col gap-1">
              {SAMPLE_QUESTIONS.slice(0, 3).map(q => (
                <button
                  key={q}
                  onClick={() => sendQuery(q)}
                  disabled={querying}
                  className="text-left text-xs text-indigo-400 hover:text-indigo-300 transition-colors truncate disabled:opacity-50"
                >
                  → {q}
                </button>
              ))}
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
            {messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="p-3 border-t border-gray-800">
            <div className="flex gap-2">
              <input
                type="text"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendQuery(input)}
                placeholder="Ask about orders, deliveries, payments…"
                disabled={querying}
                className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-3 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-indigo-500 transition-colors disabled:opacity-50"
              />
              <button
                onClick={() => sendQuery(input)}
                disabled={querying || !input.trim()}
                className="bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-xl px-3 py-2.5 transition-colors"
              >
                {querying ? <Loader2 size={16} className="animate-spin text-white" /> : <Send size={16} className="text-white" />}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
