import * as React from "react";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  description?: string;
}

export function Card({
  className,
  title,
  description,
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={twMerge(
        clsx(
          "rounded-lg border border-slate-200 bg-white p-6 shadow-sm",
          className,
        ),
      )}
      {...props}
    >
      {title ? (
        <div className="mb-4">
          <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
          {description ? (
            <p className="text-sm text-slate-500 mt-1">{description}</p>
          ) : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}
