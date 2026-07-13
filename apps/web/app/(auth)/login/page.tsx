"use client"

import { signIn } from "next-auth/react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"

export default function LoginPage() {
  return (
    <Card className="shadow-lg">
      <CardHeader className="text-center pb-2">
        <div className="flex justify-center mb-4">
          <div className="w-16 h-16 bg-slate-800 rounded-xl flex items-center justify-center">
            <span className="text-2xl font-bold text-white">SA</span>
          </div>
        </div>
        <CardTitle className="text-xl">Stock Analyst AI</CardTitle>
        <p className="text-sm text-muted-foreground mt-1">
          Sign in to access your research platform
        </p>
      </CardHeader>
      <CardContent className="pt-4">
        <Button
          className="w-full"
          onClick={() => signIn("keycloak")}
        >
          Sign in with your organization
        </Button>
      </CardContent>
    </Card>
  )
}
