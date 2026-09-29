// SPDX-License-Identifier: AGPL-3.0-only
// imaglr tags, entered exactly like tags in Stash: Stash's own react-select, set up the way Stash's
// TagSelect is (ui/v2.5/src/components/Shared/Select.tsx) - pills in one box, suggestions as you type,
// Enter to pick, Backspace to remove. The difference is what "Add" does: imaglr tags are plain text,
// so it never creates a tag in Stash.
import React from "react";
import { runOperation } from "../api.ts";
import { checkNewTag, MAX_TAGS, spareSuggestions } from "../lib/tags.ts";
import type { Suggestions } from "../lib/types.ts";

interface Option {
  value: string;
  label: string;
  isNew?: boolean;
}

interface Props {
  tags: string[];
  suggestions: Suggestions;
  lowercase: boolean;
  disabled?: boolean;
  onChange: (tags: string[]) => void;
}

// Same overrides as Stash's Select.tsx, so the field matches its tag fields exactly.
const STYLES = {
  option: (base: object) => ({ ...base, color: "#000" }),
  container: (base: { zIndex?: number }, state: { isFocused: boolean }) => ({ ...base, zIndex: state.isFocused ? 10 : base.zIndex }),
  multiValueRemove: (base: { color?: string }, state: { isFocused: boolean }) => ({ ...base, color: state.isFocused ? base.color : "#333333" }),
};

const toOption = (tag: string): Option => ({ value: tag, label: tag });

export function TagField({ tags, suggestions, lowercase, disabled, onChange }: Props) {
  const Select = PluginApi.libraries.ReactSelect.default;
  const [input, setInput] = React.useState("");
  const [found, setFound] = React.useState<string[]>([]);
  const [message, setMessage] = React.useState<string | null>(null);
  const spare = spareSuggestions(suggestions, tags);

  // Matches as you type: tags sent before, then Stash tag names.
  React.useEffect(() => {
    const q = input.trim();
    if (!q) {
      setFound([]);
      return;
    }
    const timer = window.setTimeout(() => {
      runOperation<{ tags: string[] }>("tags_suggest", { q }).then((r) => setFound(r.tags), () => setFound([]));
    }, 200);
    return () => window.clearTimeout(timer);
  }, [input]);

  const taken = new Set(tags.map((t) => t.toLowerCase()));
  const q = input.trim().toLowerCase();
  const names = q ? [...spare.addable.filter((t) => t.toLowerCase().includes(q)), ...found] : spare.addable;
  const options: Option[] = names
    .filter((t, i) => !taken.has(t.toLowerCase()) && names.findIndex((o) => o.toLowerCase() === t.toLowerCase()) === i)
    .map(toOption);
  const typed = checkNewTag(tags, input, lowercase);
  if (input.trim() && typed.ok && !options.some((o) => o.value.toLowerCase() === typed.tag.toLowerCase())) {
    options.push({ value: typed.tag, label: `Add "${typed.tag}"`, isNew: true }); // last, as in Stash
  }

  function change(selected: readonly Option[] | null) {
    const next = (selected ?? []).map((o) => o.value);
    if (next.length > MAX_TAGS) {
      setMessage(`imaglr allows ${MAX_TAGS} tags per post. Remove one first.`);
      return;
    }
    setMessage(null);
    setInput("");
    onChange(next);
  }

  return (
    <div className="imaglr-tags">
      <div className="imaglr-tags-header">
        <label htmlFor="imaglr-tag-field"><strong>Tags</strong></label>
        <span className={tags.length >= MAX_TAGS ? "text-warning" : "text-muted"}>{tags.length} / {MAX_TAGS}</span>
      </div>
      <Select
        inputId="imaglr-tag-field"
        className="react-select tag-select imaglr-tag-select"
        classNamePrefix="react-select"
        isMulti
        isClearable
        isDisabled={disabled}
        closeMenuOnSelect={false}
        value={tags.map(toOption)}
        options={options}
        inputValue={input}
        onInputChange={(value: string, meta: { action: string }) => {
          if (meta.action === "input-change") {
            setInput(value);
            setMessage(null);
          }
        }}
        onChange={change}
        filterOption={() => true}
        placeholder="Add tags…"
        noOptionsMessage={() => (input.trim() && !typed.ok ? typed.error : null)}
        styles={STYLES}
        components={{ IndicatorSeparator: () => null }}
      />
      {message ? <div className="small text-warning mt-1">{message}</div> : null}
      {spare.tooLong.length ? (
        <div className="small text-muted mt-1">
          Not usable on imaglr (over 64 characters): {spare.tooLong.join(", ")}
        </div>
      ) : null}
    </div>
  );
}
