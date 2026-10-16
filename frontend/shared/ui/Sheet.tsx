"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { IconButton } from "./primitives";

/** Right-hand side sheet (Radix Dialog: focus trap, Esc, restore focus). */
export function Sheet({
  open,
  onClose,
  title,
  description,
  eyebrow,
  children,
  footer,
  width = 480,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: React.ReactNode;
  eyebrow?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="a-scrim fixed inset-0 z-50 bg-[var(--scrim)]" />
        <Dialog.Content
          className="a-sheet fixed inset-y-2 right-2 z-50 flex flex-col overflow-hidden rounded-lg bg-raised shadow-overlay outline-none"
          style={{ width: `min(${width}px, calc(100vw - 16px))` }}
        >
          <div className="flex items-start gap-3 border-b border-line-subtle px-5 pb-4 pt-4">
            <div className="min-w-0 flex-1">
              {eyebrow ? <div className="mb-1 text-[12px] text-muted">{eyebrow}</div> : null}
              <Dialog.Title className="font-serif text-[20px] leading-tight text-fg">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="mt-1 text-[13px] text-muted">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <IconButton label="Close" size="sm" className="-mr-1">
                <X className="h-4 w-4" />
              </IconButton>
            </Dialog.Close>
          </div>
          <div className="scroll min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>
          {footer ? <div className="border-t border-line-subtle bg-surface px-5 py-4 dark:bg-raised">{footer}</div> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
