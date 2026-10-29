export function DzLogo({
  size = 32,
  className,
  mode = "solid",
}: {
  size?: number;
  className?: string;
  mode?: "solid" | "line";
}) {
  if (mode === "solid") {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 64 64"
        fill="var(--dz-orange)"
        className={className}
      />
    );
  }
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      stroke="var(--dz-orange)"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    />
  );
}