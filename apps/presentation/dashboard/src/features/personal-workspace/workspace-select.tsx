import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export type WorkspaceSelectOption = {
  disabled?: boolean;
  group?: string;
  label: string;
  value: string;
};

export function WorkspaceSelect({
  ariaLabel,
  className,
  icon,
  onChange,
  options,
  prefixLabel,
  value,
}: {
  ariaLabel: string;
  className?: string;
  icon?: ReactNode;
  onChange: (value: string) => void;
  options: WorkspaceSelectOption[];
  prefixLabel?: string;
  value: string;
}) {
  const listboxId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef(new Map<string, HTMLButtonElement>());
  const [open, setOpen] = useState(false);
  const [activeValue, setActiveValue] = useState(value);
  const selected = options.find((option) => option.value === value) ?? options[0];
  const enabledOptions = options.filter((option) => !option.disabled);

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    optionRefs.current.get(activeValue)?.focus();
  }, [activeValue, open]);

  function focusOption(nextValue: string) {
    setActiveValue(nextValue);
  }

  function openList(direction: "first" | "last" | "selected" = "selected") {
    const fallback = direction === "last" ? enabledOptions.at(-1) : enabledOptions[0];
    const next = direction === "selected" && selected && !selected.disabled ? selected : fallback;
    if (!next) return;
    setOpen(true);
    focusOption(next.value);
  }

  function closeList({ restoreFocus = false } = {}) {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  }

  function selectOption(option: WorkspaceSelectOption) {
    if (option.disabled) return;
    onChange(option.value);
    closeList({ restoreFocus: true });
  }

  function moveActive(direction: 1 | -1) {
    if (!enabledOptions.length) return;
    const currentIndex = enabledOptions.findIndex((option) => option.value === activeValue);
    const nextIndex = currentIndex < 0
      ? 0
      : (currentIndex + direction + enabledOptions.length) % enabledOptions.length;
    focusOption(enabledOptions[nextIndex].value);
  }

  function handleTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openList("selected");
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      openList("last");
    }
  }

  function handleOptionKeyDown(event: KeyboardEvent<HTMLButtonElement>, option: WorkspaceSelectOption) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActive(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(-1);
    } else if (event.key === "Home") {
      event.preventDefault();
      if (enabledOptions[0]) focusOption(enabledOptions[0].value);
    } else if (event.key === "End") {
      event.preventDefault();
      const last = enabledOptions.at(-1);
      if (last) focusOption(last.value);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      selectOption(option);
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeList({ restoreFocus: true });
    } else if (event.key === "Tab") {
      closeList();
    }
  }

  let previousGroup: string | undefined;
  return (
    <div className={`personal-select${className ? ` ${className}` : ""}`} ref={rootRef}>
      <button
        aria-controls={listboxId}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        className="personal-select-trigger"
        data-value={value}
        onClick={() => open ? closeList() : openList()}
        onKeyDown={handleTriggerKeyDown}
        ref={triggerRef}
        role="combobox"
        type="button"
      >
        {icon ? <span className="personal-select-icon">{icon}</span> : null}
        <span className="personal-select-value">
          {prefixLabel ? <small>{prefixLabel}</small> : null}
          <span>{selected?.label ?? value}</span>
        </span>
        <ChevronDown aria-hidden className={open ? "is-open" : undefined} size={14} />
      </button>
      {open ? (
        <div aria-label={ariaLabel} className="personal-select-listbox" id={listboxId} role="listbox">
          {options.map((option) => {
            const showGroup = option.group && option.group !== previousGroup;
            previousGroup = option.group;
            return (
              <div className="personal-select-option-wrap" key={option.value}>
                {showGroup ? <div className="personal-select-group-label">{option.group}</div> : null}
                <button
                  aria-disabled={option.disabled || undefined}
                  aria-selected={option.value === value}
                  className="personal-select-option"
                  disabled={option.disabled}
                  id={`${listboxId}-${option.value.replace(/[^a-z0-9_-]/gi, "-")}`}
                  onClick={() => selectOption(option)}
                  onFocus={() => setActiveValue(option.value)}
                  onKeyDown={(event) => handleOptionKeyDown(event, option)}
                  ref={(node) => {
                    if (node) optionRefs.current.set(option.value, node);
                    else optionRefs.current.delete(option.value);
                  }}
                  role="option"
                  tabIndex={option.value === activeValue ? 0 : -1}
                  type="button"
                >
                  <span>{option.label}</span>
                  {option.value === value ? <Check aria-hidden size={15} /> : null}
                </button>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
