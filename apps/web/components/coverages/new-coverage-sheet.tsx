"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { Plus } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet"
import { useToast } from "@/hooks/use-toast"
import { useCreateCoverage, useIndustries } from "@/lib/queries/coverages"
import { EXCHANGES } from "@/lib/types"

export function NewCoverageSheet() {
  const router = useRouter()
  const { toast } = useToast()
  const { data: industries } = useIndustries()
  const createCoverage = useCreateCoverage()

  const [open, setOpen] = useState(false)
  const [ticker, setTicker] = useState("")
  const [companyName, setCompanyName] = useState("")
  const [exchange, setExchange] = useState<string>(EXCHANGES[0])
  const [industryId, setIndustryId] = useState<string>("")

  function reset() {
    setTicker("")
    setCompanyName("")
    setExchange(EXCHANGES[0])
    setIndustryId("")
  }

  function handleOpenChange(next: boolean) {
    if (!next) reset()
    setOpen(next)
  }

  function handleSubmit() {
    if (!ticker.trim() || !companyName.trim()) return
    createCoverage.mutate(
      {
        ticker: ticker.trim(),
        companyName: companyName.trim(),
        exchange,
        industryId: industryId || null,
      },
      {
        onSuccess: (coverage) => {
          handleOpenChange(false)
          router.push(`/coverages/${coverage.id}/documents`)
        },
        onError: (error) => {
          toast({
            title: "Failed to create coverage",
            description: error instanceof Error ? error.message : "Please try again.",
            variant: "destructive",
          })
        },
      }
    )
  }

  const canSubmit = ticker.trim().length > 0 && companyName.trim().length > 0

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetTrigger asChild>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          New Coverage
        </Button>
      </SheetTrigger>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>New Coverage</SheetTitle>
          <SheetDescription>Start tracking a new ticker for research.</SheetDescription>
        </SheetHeader>

        <div className="mt-6 space-y-4">
          <div className="space-y-2">
            <Label htmlFor="ticker">Ticker</Label>
            <Input
              id="ticker"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              placeholder="AAPL"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="company-name">Company Name</Label>
            <Input
              id="company-name"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="Apple Inc."
            />
          </div>

          <div className="space-y-2">
            <Label>Exchange</Label>
            <Select value={exchange} onValueChange={setExchange}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXCHANGES.map((ex) => (
                  <SelectItem key={ex} value={ex}>
                    {ex}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Industry</Label>
            <Select value={industryId} onValueChange={setIndustryId}>
              <SelectTrigger>
                <SelectValue placeholder="Select an industry" />
              </SelectTrigger>
              <SelectContent>
                {industries?.map((industry) => (
                  <SelectItem key={industry.id} value={industry.id}>
                    {industry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Button className="w-full" disabled={!canSubmit || createCoverage.isPending} onClick={handleSubmit}>
            {createCoverage.isPending ? "Creating…" : "Create Coverage"}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
