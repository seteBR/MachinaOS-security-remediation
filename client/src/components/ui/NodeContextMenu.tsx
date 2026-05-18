/**
 * NodeContextMenu - Right-click context menu for nodes
 *
 * Provides actions: Rename, Copy, Delete
 * Hand-rolled positioning at cursor coords (Radix DropdownMenu attaches to
 * a trigger, which doesn't fit the right-click-anywhere pattern). Visual
 * style mirrors shadcn DropdownMenuContent so it lives consistently with
 * the rest of the surface.
 */
import React, { useEffect, useRef, useCallback, useMemo } from 'react';
import { Pencil, Copy as CopyIcon, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface NodeContextMenuProps {
  nodeId: string;
  x: number;
  y: number;
  onClose: () => void;
  onRename: () => void;
  onCopy: () => void;
  onDelete: () => void;
}

interface MenuItem {
  label: string;
  shortcut: string;
  action: () => void;
  Icon: typeof Pencil;
  danger?: boolean;
}

const NodeContextMenu: React.FC<NodeContextMenuProps> = ({
  nodeId: _nodeId,
  x,
  y,
  onClose,
  onRename,
  onCopy,
  onDelete,
}) => {
  const menuRef = useRef<HTMLDivElement>(null);
  const [focusedIndex, setFocusedIndex] = React.useState(0);

  const menuItems: MenuItem[] = useMemo(() => [
    { label: 'Rename', shortcut: 'F2',     action: onRename, Icon: Pencil },
    { label: 'Copy',   shortcut: 'Ctrl+C', action: onCopy,   Icon: CopyIcon },
    { label: 'Delete', shortcut: 'Del',    action: onDelete, Icon: Trash2, danger: true },
  ], [onRename, onCopy, onDelete]);

  // Calculate menu position to avoid overflow
  const getMenuPosition = useCallback(() => {
    const menuWidth = 180;
    const menuHeight = menuItems.length * 36 + 16;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let left = x;
    let top = y;

    if (x + menuWidth > viewportWidth) {
      left = viewportWidth - menuWidth - 8;
    }
    if (y + menuHeight > viewportHeight) {
      top = viewportHeight - menuHeight - 8;
    }

    return { left, top };
  }, [x, y, menuItems.length]);

  const position = getMenuPosition();

  // Click outside / Escape
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose();
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    const timeoutId = setTimeout(() => {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleEscape);
    }, 0);
    return () => {
      clearTimeout(timeoutId);
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [onClose]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      switch (event.key) {
        case 'ArrowDown':
          event.preventDefault();
          setFocusedIndex((prev) => (prev + 1) % menuItems.length);
          break;
        case 'ArrowUp':
          event.preventDefault();
          setFocusedIndex((prev) => (prev - 1 + menuItems.length) % menuItems.length);
          break;
        case 'Enter':
          event.preventDefault();
          menuItems[focusedIndex].action();
          onClose();
          break;
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [focusedIndex, menuItems, onClose]);

  useEffect(() => {
    menuRef.current?.focus();
  }, []);

  const handleItemClick = (item: MenuItem) => {
    item.action();
    onClose();
  };

  return (
    <div
      ref={menuRef}
      tabIndex={-1}
      // Position is dynamic (cursor coords) — must stay inline.
      style={{ left: position.left, top: position.top }}
      className="fixed z-[10000] min-w-[160px] rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-md outline-none"
    >
      {menuItems.map((item, index) => {
        const focused = focusedIndex === index;
        return (
          <div
            key={item.label}
            onClick={() => handleItemClick(item)}
            onMouseEnter={() => setFocusedIndex(index)}
            className={cn(
              'flex cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
              focused && 'bg-muted',
              item.danger ? 'text-destructive' : 'text-foreground'
            )}
          >
            <div className="flex items-center gap-2">
              <item.Icon className="h-3.5 w-3.5" />
              <span className="font-medium">{item.label}</span>
            </div>
            <span className="font-mono text-xs text-muted-foreground">
              {item.shortcut}
            </span>
          </div>
        );
      })}
    </div>
  );
};

export default NodeContextMenu;
