import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";
import AuthInitializer from "@/components/auth/AuthInitializer";
import ThemeProvider from "@/components/ThemeProvider";
import { Providers } from "@/components/Providers";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: "SoldierIQ - Knowledge Management",
  description: "Tactical Intelligence Knowledge Management System",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={cn("font-sans", geist.variable)}>
      <head>
        <link
          href="https://assets.calendly.com/assets/external/widget.css"
          rel="stylesheet"
        />
      </head>
      <body>
        <Providers>
          <ThemeProvider>
            <AuthInitializer />
            {children}
          </ThemeProvider>
        </Providers>
        <Script
          src="https://assets.calendly.com/assets/external/widget.js"
          strategy="lazyOnload"
        />
      </body>
    </html>
  );
}
