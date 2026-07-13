import type { NextAuthOptions } from "next-auth"
import KeycloakProvider from "next-auth/providers/keycloak"

const ROLE_PRIORITY = ["admin", "senior_analyst", "analyst", "viewer"] as const

export const authOptions: NextAuthOptions = {
  providers: [
    KeycloakProvider({
      clientId: process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID!,
      clientSecret: "",
      issuer: `${process.env.NEXT_PUBLIC_KEYCLOAK_URL}/realms/stock-analyst`,
    }),
  ],
  session: {
    strategy: "jwt",
  },
  callbacks: {
    async jwt({ token, account, profile }) {
      if (account && profile) {
        token.accessToken = account.access_token
        token.tenant_id = (profile as Record<string, unknown>).tenant_id as string
        const roles: string[] =
          ((profile as Record<string, unknown>).realm_access as Record<string, string[]>)
            ?.roles ?? []
        token.role =
          ROLE_PRIORITY.find((r) => roles.includes(r)) ?? "viewer"
      }
      return token
    },
    async session({ session, token }) {
      session.accessToken = token.accessToken as string | undefined
      if (session.user) {
        session.user.tenant_id = (token.tenant_id as string) ?? ""
        session.user.role = (token.role as string) ?? "viewer"
      }
      return session
    },
  },
  pages: {
    signIn: "/login",
  },
}
