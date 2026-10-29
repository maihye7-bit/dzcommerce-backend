import type { ButtonHTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/* DzCommerce Apple iOS-style buttons */
const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-lg transition-all duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary: "flex h-10 py-2 px-6 text-sm font-medium text-white bg-orange-600 hover:bg-orange-500 active:bg-orange-400",
        secondary: "flex h-10 py-2 px-6 text-sm font-medium text-gray-800 bg-white hover:bg-gray-100 active:bg-gray-200",
        outline: "flex h-10 py-2 px-6 text-sm font-medium text-gray-700 border border-gray-300 bg-white hover:bg-gray-50 active:bg-gray-100",
        ghost: "flex h-10 py-2 px-6 text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-800",
        default: "flex h-10 py-2 px-6 text-sm font-medium text-white bg-primary-600 hover:bg-primary-500 active:bg-primary-400",
      },
      size: {
        default: "h-10 py-2 px-6",
        sm: "h-9 py-1.5 px-3",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  },
);

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants>;

export function Button({
  className,
  variant,
  size,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(buttonVariants({ variant, size }), className)}
      type="button"
      {...props}
    />
  );
}
