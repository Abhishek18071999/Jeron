import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Jeron",
  description: "Personal research and decision support for Indian equities",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
