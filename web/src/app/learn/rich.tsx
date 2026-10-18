import Link from "next/link";

// **bold** and [links](/path) inside lesson text.
export function Rich({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**"))
          return (
            <strong key={i} className="font-semibold text-fg">
              {part.slice(2, -2)}
            </strong>
          );
        const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        if (link)
          return (
            <Link key={i} href={link[2]} className="font-medium text-accent underline-offset-2 hover:underline">
              {link[1]}
            </Link>
          );
        return part;
      })}
    </>
  );
}
