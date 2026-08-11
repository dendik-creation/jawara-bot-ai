"use client"

import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { api, GatewayError, type AiMlOverview } from "@/lib/api"

function StatRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

export function AiMlOverviewGrid() {
  const [data, setData] = React.useState<AiMlOverview | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.aiMlOverview(controller.signal)
        if (cancelled) return
        setData(result)
      } catch (caught) {
        if (cancelled) return
        setError(caught instanceof GatewayError ? caught.message : "gateway tidak dapat dihubungi")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [])

  if (error) return <p className="text-sm text-muted-foreground">{error}</p>

  if (loading || !data) {
    return (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Skeleton key={index} className="h-40 w-full" />
        ))}
      </div>
    )
  }

  const kb = data.knowledge_base
  const rules = data.detection_rules
  const policies = data.policies
  const datasets = data.datasets
  const feedback = data.feedback
  const trainingJobs = data.training_jobs
  const evaluation = data.evaluation
  const modelRegistry = data.model_registry
  const ml = data.ml_service

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>Knowledge Base</CardTitle>
          <CardDescription>Fact items yang bisa ditarik ML Service.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {kb.available ? (
            <>
              <StatRow label="Total fact item" value={kb.total_facts} />
              <StatRow label="Aktif" value={kb.active_facts} />
              <StatRow label="Tersinkron" value={kb.synced} />
              <StatRow label="Belum disinkron" value={kb.never_synced} />
              <StatRow label="Gagal sinkron" value={kb.sync_failed} />
              <StatRow label="Sumber" value={kb.total_sources} />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({kb.reason}).</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Detection Rules</CardTitle>
          <CardDescription>Sebaran status rule deteksi.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {rules.available ? (
            <>
              <StatRow label="Total" value={rules.total} />
              {Object.entries(rules.by_status).map(([status, count]) => (
                <StatRow key={status} label={status} value={count} />
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({rules.reason}).</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Security Policies</CardTitle>
          <CardDescription>Sebaran status policy.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {policies.available ? (
            <>
              <StatRow label="Total" value={policies.total} />
              {Object.entries(policies.by_status).map(([status, count]) => (
                <StatRow key={status} label={status} value={count} />
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({policies.reason}).</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Datasets</CardTitle>
          <CardDescription>Sebaran status dataset latih.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {datasets.available ? (
            <>
              <StatRow label="Total" value={datasets.total} />
              {Object.entries(datasets.by_status).map(([status, count]) => (
                <StatRow key={status} label={status} value={count} />
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({datasets.reason}).</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Operator Feedback</CardTitle>
          <CardDescription>Koreksi human-in-the-loop dari Threats.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {feedback.available ? (
            <>
              <StatRow label="Total" value={feedback.total} />
              {Object.entries(feedback.by_type).map(([type, count]) => (
                <StatRow key={type} label={type} value={count} />
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({feedback.reason}).</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>ML Service</CardTitle>
          <CardDescription>Status inference dan vector store — data operasional terkini.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {ml.available ? (
            <>
              <StatRow label="Status" value={<Badge variant={ml.status === "ready" ? "low" : "high"}>{ml.status}</Badge>} />
              <StatRow label="Embedder" value={ml.embedder ?? "—"} />
              <StatRow label="LLM" value={ml.llm ?? "—"} />
              {ml.degraded_reasons.length > 0 ? (
                <StatRow label="Degraded" value={ml.degraded_reasons.join(", ")} />
              ) : null}
              {ml.vector_store.available ? (
                <>
                  <StatRow label="Qdrant collection" value={ml.vector_store.collection} />
                  <StatRow label="Points" value={ml.vector_store.points_count} />
                </>
              ) : (
                <StatRow label="Vector store" value="tidak terjangkau" />
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({ml.reason}).</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Training Jobs</CardTitle>
          <CardDescription>Sebaran status job — eksekusi ML Service belum diimplementasikan.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {trainingJobs.available ? (
            <>
              <StatRow label="Total" value={trainingJobs.total} />
              {Object.entries(trainingJobs.by_status).map(([status, count]) => (
                <StatRow key={status} label={status} value={count} />
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({trainingJobs.reason}).</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Evaluation</CardTitle>
          <CardDescription>Sebaran status evaluasi — butuh training job COMPLETED, eksekusi ML Service belum diimplementasikan.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {evaluation.available ? (
            <>
              <StatRow label="Total" value={evaluation.total} />
              {Object.entries(evaluation.by_status).map(([status, count]) => (
                <StatRow key={status} label={status} value={count} />
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({evaluation.reason}).</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Model Registry</CardTitle>
          <CardDescription>Sebaran status model version — CANDIDATE muncul otomatis begitu evaluasi selesai.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {modelRegistry.available ? (
            <>
              <StatRow label="Total" value={modelRegistry.total} />
              {Object.entries(modelRegistry.by_status).map(([status, count]) => (
                <StatRow key={status} label={status} value={count} />
              ))}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Belum tersedia ({modelRegistry.reason}).</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
