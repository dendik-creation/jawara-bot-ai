"use client"

import * as React from "react"

import { useAuth } from "@/components/auth/auth-provider"
import { severityVariant } from "@/components/dashboard/incident-list"
import { Badge, riskVariant } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { toast } from "@/components/ui/toast"
import {
  api,
  GatewayError,
  type IncidentDetail as IncidentDetailData,
  type IncidentSeverity,
  type IncidentState,
} from "@/lib/api"

const SEVERITIES: IncidentSeverity[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

function stateVariant(state: IncidentState): "low" | "high" | "medium" | "unknown" {
  if (state === "RESOLVED" || state === "FALSE_POSITIVE") return "low"
  if (state === "OPEN") return "high"
  if (state === "INVESTIGATING") return "medium"
  return "unknown"
}

export function IncidentDetail({ id }: { id: string }) {
  const { operator } = useAuth()
  const [data, setData] = React.useState<IncidentDetailData | null>(null)
  const [loading, setLoading] = React.useState(true)
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [closing, setClosing] = React.useState(false)
  const [refreshKey, setRefreshKey] = React.useState(0)

  React.useEffect(() => {
    let cancelled = false
    const controller = new AbortController()

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const result = await api.incident(id, controller.signal)
        if (!cancelled) setData(result)
      } catch (caught) {
        if (!cancelled) setError(caught instanceof GatewayError ? caught.message : "gateway tidak dapat dihubungi")
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [id, refreshKey])

  function refresh() {
    setRefreshKey((key) => key + 1)
  }

  async function runAction(
    action: "ASSIGN_TO_ME" | "SET_STATE" | "SET_SEVERITY" | "ESCALATE",
    opts: { state?: IncidentState; severity?: IncidentSeverity } = {},
  ) {
    setBusy(true)
    try {
      await api.actionOnIncident(id, action, opts)
      refresh()
      const label =
        action === "ASSIGN_TO_ME"
          ? "Incident ditugaskan ke kamu"
          : action === "SET_STATE"
            ? `State diganti ke ${opts.state}`
            : action === "SET_SEVERITY"
              ? `Severity diganti ke ${opts.severity}`
              : "Incident dieskalasi"
      toast.success(label)
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menjalankan aksi")
    } finally {
      setBusy(false)
    }
  }

  if (loading && !data) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  if (error && !data) {
    return <p className="text-sm text-muted-foreground">{error}</p>
  }

  if (!data) {
    return <p className="text-sm text-muted-foreground">Incident tidak ditemukan.</p>
  }

  const isMine = operator?.id === data.assigned_operator_id
  const isClosed = data.state === "RESOLVED" || data.state === "FALSE_POSITIVE"

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-4">
          <div className="flex flex-col gap-1">
            <span className="font-mono text-xs text-muted-foreground">{data.code}</span>
            <CardTitle className="text-lg">{data.title}</CardTitle>
            <CardDescription>
              Dibuat oleh {data.created_by_name} · {new Date(data.created_at).toLocaleString("id-ID")}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={severityVariant(data.severity)}>{data.severity}</Badge>
            <Badge variant={stateVariant(data.state)}>{data.state}</Badge>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error ? <p className="text-sm text-destructive">{error}</p> : null}

          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-xs text-muted-foreground">Ditugaskan</dt>
              <dd>{data.assigned_operator_name ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Pesan</dt>
              <dd>{data.message_count}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Pengguna terdampak</dt>
              <dd>{data.affected_user_count}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Kategori</dt>
              <dd>{data.categories.length > 0 ? data.categories.join(", ") : "—"}</dd>
            </div>
          </dl>

          {isClosed && data.resolution_reason ? (
            <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
              Ditutup: {data.resolution_reason}
            </p>
          ) : null}

          {!isClosed ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
              <Button variant="outline" size="sm" disabled={isMine || busy} onClick={() => runAction("ASSIGN_TO_ME")}>
                {isMine ? "Ditugaskan ke saya" : "Assign ke saya"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || data.state === "INVESTIGATING"}
                onClick={() => runAction("SET_STATE", { state: "INVESTIGATING" })}
              >
                Tandai Investigating
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy || data.state === "CONTAINED"}
                onClick={() => runAction("SET_STATE", { state: "CONTAINED" })}
              >
                Tandai Contained
              </Button>
              <Select
                value={data.severity}
                onValueChange={(value) => runAction("SET_SEVERITY", { severity: value as IncidentSeverity })}
              >
                <SelectTrigger size="sm" className="h-8 w-[150px]" aria-label="Ubah severity">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SEVERITIES.map((value) => (
                    <SelectItem key={value} value={value}>
                      {value}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" disabled={busy} onClick={() => runAction("ESCALATE")}>
                Escalate
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="ml-auto text-destructive hover:text-destructive"
                disabled={busy}
                onClick={() => setClosing(true)}
              >
                Tutup Incident
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <ThreatsCard incidentId={id} threats={data.threats} onChanged={refresh} />
      <NotesCard incidentId={id} notes={data.notes} onChanged={refresh} />

      <CloseIncidentDialog open={closing} onClose={() => setClosing(false)} onDone={() => { setClosing(false); refresh() }} incidentId={id} />
    </div>
  )
}

function ThreatsCard({
  incidentId,
  threats,
  onChanged,
}: {
  incidentId: string
  threats: IncidentDetailData["threats"]
  onChanged: () => void
}) {
  const [newId, setNewId] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function addThreat() {
    if (!newId.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.addThreatToIncident(incidentId, newId.trim())
      setNewId("")
      onChanged()
      toast.success("Threat ditambahkan ke incident")
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menambahkan threat")
    } finally {
      setBusy(false)
    }
  }

  async function removeThreat(messageLogId: string) {
    setBusy(true)
    setError(null)
    try {
      await api.removeThreatFromIncident(incidentId, messageLogId)
      onChanged()
      toast.success("Threat dihapus dari incident")
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menghapus threat")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Threats Terkait</CardTitle>
        <CardDescription>Pesan yang membentuk cakupan incident ini.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {threats.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada threat terkait.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Waktu</TableHead>
                  <TableHead>Risiko</TableHead>
                  <TableHead>Kategori</TableHead>
                  <TableHead className="w-20">
                    <span className="sr-only">Aksi</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {threats.map((threat) => (
                  <TableRow key={threat.message_log_id}>
                    <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                      {new Date(threat.at).toLocaleString("id-ID")}
                    </TableCell>
                    <TableCell>
                      <Badge variant={riskVariant(threat.risk)}>{threat.risk}</Badge>
                    </TableCell>
                    <TableCell className="text-sm">{threat.threat_category}</TableCell>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => removeThreat(threat.message_log_id)}
                      >
                        Hapus
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        <div className="flex items-end gap-2">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label className="text-xs text-muted-foreground">Tambah threat (message log id)</Label>
            <Input
              value={newId}
              onChange={(event) => setNewId(event.target.value)}
              placeholder="message_log_id"
              className="font-mono text-xs"
            />
          </div>
          <Button size="sm" disabled={!newId.trim() || busy} onClick={addThreat}>
            Tambah
          </Button>
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </CardContent>
    </Card>
  )
}

function NotesCard({
  incidentId,
  notes,
  onChanged,
}: {
  incidentId: string
  notes: IncidentDetailData["notes"]
  onChanged: () => void
}) {
  const [note, setNote] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    if (!note.trim()) return
    setBusy(true)
    setError(null)
    try {
      await api.addIncidentNote(incidentId, note.trim())
      setNote("")
      onChanged()
      toast.success("Catatan ditambahkan")
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menambahkan catatan")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Catatan Investigasi</CardTitle>
        <CardDescription>Timeline — tidak bisa dihapus setelah ditambahkan.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {notes.length === 0 ? (
          <p className="text-sm text-muted-foreground">Belum ada catatan.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {notes.map((entry) => (
              <li key={entry.id} className="border-l-2 border-border pl-3 text-sm">
                <p>{entry.note}</p>
                <p className="text-xs text-muted-foreground">
                  {entry.author_name} · {new Date(entry.at).toLocaleString("id-ID")}
                </p>
              </li>
            ))}
          </ul>
        )}

        <div className="flex flex-col gap-2">
          <Textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Tambahkan catatan investigasi…"
            rows={3}
          />
          <div className="flex items-center justify-between">
            {error ? <p className="text-sm text-destructive">{error}</p> : <span />}
            <Button size="sm" disabled={!note.trim() || busy} onClick={submit}>
              Tambah Catatan
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function CloseIncidentDialog({
  open,
  onClose,
  onDone,
  incidentId,
}: {
  open: boolean
  onClose: () => void
  onDone: () => void
  incidentId: string
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        {open ? <CloseIncidentForm incidentId={incidentId} onClose={onClose} onDone={onDone} /> : null}
      </DialogContent>
    </Dialog>
  )
}

function CloseIncidentForm({
  incidentId,
  onClose,
  onDone,
}: {
  incidentId: string
  onClose: () => void
  onDone: () => void
}) {
  const [state, setState] = React.useState<"RESOLVED" | "FALSE_POSITIVE" | "">("")
  const [reason, setReason] = React.useState("")
  const [submitting, setSubmitting] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    if (!state || !reason.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await api.actionOnIncident(incidentId, "CLOSE", { state, reason: reason.trim() })
      onDone()
      toast.success("Incident ditutup", { description: state === "RESOLVED" ? "Ditandai resolved." : "Ditandai false positive." })
    } catch (caught) {
      setError(caught instanceof GatewayError ? caught.message : "gagal menutup incident")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Tutup Incident</DialogTitle>
        <DialogDescription>Wajib disertai alasan — tercatat di Audit Log.</DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Hasil</Label>
          <Select value={state} onValueChange={(value) => setState(value as "RESOLVED" | "FALSE_POSITIVE")}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Pilih hasil" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="RESOLVED">Resolved — selesai ditangani</SelectItem>
              <SelectItem value="FALSE_POSITIVE">False Positive — bukan ancaman</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Alasan</Label>
          <Textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} />
        </div>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={submitting}>
          Batal
        </Button>
        <Button onClick={submit} disabled={!state || !reason.trim() || submitting}>
          {submitting ? "Menyimpan…" : "Tutup Incident"}
        </Button>
      </DialogFooter>
    </>
  )
}
