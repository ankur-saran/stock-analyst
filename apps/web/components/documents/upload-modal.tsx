"use client"

import { useCallback, useEffect, useState } from "react"
import { useDropzone, type FileRejection } from "react-dropzone"
import { FileText, Loader2, UploadCloud } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/hooks/use-toast"
import { useFetchFromSEC, useUploadDocument } from "@/lib/queries/documents"
import { FILING_TYPES, SEC_FILING_TYPES } from "@/lib/types"
import { cn } from "@/lib/utils"

const MAX_UPLOAD_BYTES = 100 * 1024 * 1024

interface UploadModalProps {
  coverageId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  initialTab?: "upload" | "sec"
  defaultTicker?: string
}

export function UploadModal({
  coverageId,
  open,
  onOpenChange,
  initialTab = "upload",
  defaultTicker = "",
}: UploadModalProps) {
  const { toast } = useToast()
  const [tab, setTab] = useState<"upload" | "sec">(initialTab)

  // --- Upload File tab ---
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [filingType, setFilingType] = useState<string>(FILING_TYPES[0])
  const [period, setPeriod] = useState("")
  const [progress, setProgress] = useState(0)
  const uploadMutation = useUploadDocument(coverageId)

  const onDrop = useCallback((accepted: File[], rejected: FileRejection[]) => {
    setFileError(null)
    if (rejected.length > 0) {
      const code = rejected[0]?.errors[0]?.code
      if (code === "file-too-large") setFileError("File exceeds the 100MB limit")
      else if (code === "file-invalid-type") setFileError("Only PDF files are accepted")
      else setFileError("That file couldn't be accepted")
      return
    }
    setFile(accepted[0] ?? null)
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    maxSize: MAX_UPLOAD_BYTES,
    multiple: false,
  })

  // --- Fetch from SEC EDGAR tab ---
  const currentYear = new Date().getFullYear()
  const years = Array.from({ length: 5 }, (_, i) => currentYear - i)
  const [ticker, setTicker] = useState(defaultTicker)
  const [formType, setFormType] = useState<string>(SEC_FILING_TYPES[0])
  const [year, setYear] = useState<number>(currentYear)
  const secMutation = useFetchFromSEC(coverageId)

  // Re-sync transient form state whenever the modal is (re)opened.
  useEffect(() => {
    if (open) {
      setTab(initialTab)
      setFile(null)
      setFileError(null)
      setFilingType(FILING_TYPES[0])
      setPeriod("")
      setProgress(0)
      setTicker(defaultTicker)
      setFormType(SEC_FILING_TYPES[0])
      setYear(currentYear)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialTab, defaultTicker])

  function handleUpload() {
    if (!file || !period.trim()) return
    setProgress(0)
    uploadMutation.mutate(
      { file, filingType, period: period.trim(), onProgress: setProgress },
      {
        onSuccess: () => {
          toast({ title: "Document queued for indexing" })
          onOpenChange(false)
        },
        onError: (error) => {
          toast({
            title: "Upload failed",
            description: error instanceof Error ? error.message : "Please try again.",
            variant: "destructive",
          })
        },
      }
    )
  }

  function handleFetchFromSec() {
    if (!ticker.trim()) return
    secMutation.mutate(
      { ticker: ticker.trim().toUpperCase(), formType, year },
      {
        onSuccess: () => {
          toast({ title: "Filing fetched and queued for indexing" })
          onOpenChange(false)
        },
        onError: (error) => {
          toast({
            title: "Fetch failed",
            description: error instanceof Error ? error.message : "Please try again.",
            variant: "destructive",
          })
        },
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Add Document</DialogTitle>
          <DialogDescription>Upload a filing or pull one directly from SEC EDGAR.</DialogDescription>
        </DialogHeader>

        <Tabs value={tab} onValueChange={(v) => setTab(v as "upload" | "sec")}>
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="upload">Upload File</TabsTrigger>
            <TabsTrigger value="sec">Fetch from SEC EDGAR</TabsTrigger>
          </TabsList>

          <TabsContent value="upload" className="space-y-4 pt-2">
            <div
              {...getRootProps()}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors",
                isDragActive ? "border-primary bg-primary/5" : "border-slate-200 hover:border-slate-300"
              )}
            >
              <input {...getInputProps()} />
              {file ? (
                <>
                  <FileText className="h-8 w-8 text-slate-400" />
                  <p className="text-sm font-medium text-slate-900">{file.name}</p>
                  <p className="text-xs text-slate-400">{(file.size / (1024 * 1024)).toFixed(1)} MB</p>
                </>
              ) : (
                <>
                  <UploadCloud className="h-8 w-8 text-slate-400" />
                  <p className="text-sm text-slate-600">Drag & drop a PDF here, or click to browse</p>
                  <p className="text-xs text-slate-400">PDF only, up to 100MB</p>
                </>
              )}
            </div>
            {fileError && <p className="text-sm text-red-500">{fileError}</p>}

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Filing Type</Label>
                <Select value={filingType} onValueChange={setFilingType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {FILING_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="period">Period</Label>
                <Input
                  id="period"
                  placeholder="FY2024 or Q3 2024"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                />
              </div>
            </div>

            {uploadMutation.isPending && (
              <div className="space-y-1">
                <Progress value={progress} />
                <p className="text-right text-xs text-slate-400">{progress}%</p>
              </div>
            )}

            <Button
              className="w-full"
              disabled={!file || !period.trim() || uploadMutation.isPending}
              onClick={handleUpload}
            >
              {uploadMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Uploading…
                </>
              ) : (
                "Upload"
              )}
            </Button>
          </TabsContent>

          <TabsContent value="sec" className="space-y-4 pt-2">
            <div className="space-y-2">
              <Label htmlFor="ticker">Ticker</Label>
              <Input
                id="ticker"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                placeholder="AAPL"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Filing Type</Label>
                <Select value={formType} onValueChange={setFormType}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SEC_FILING_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Year</Label>
                <Select value={String(year)} onValueChange={(v) => setYear(Number(v))}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {years.map((y) => (
                      <SelectItem key={y} value={String(y)}>
                        {y}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <Button
              className="w-full"
              disabled={!ticker.trim() || secMutation.isPending}
              onClick={handleFetchFromSec}
            >
              {secMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Fetching from SEC EDGAR…
                </>
              ) : (
                "Fetch"
              )}
            </Button>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
