/**
 * Skeleton — loading placeholders matching RuntimeCard and message shapes.
 *
 * Usage:
 *   <Skeleton.Card />        — card-shaped shimmer
 *   <Skeleton.Message />     — chat message placeholder
 *   <Skeleton.Grid count={6} cols={3} /> — responsive grid of cards
 */

import React from "react";
import { colors, radius, space, card } from "../design";


// Shared shimmer style


const shimmerBg = `linear-gradient(90deg, ${colors.borderLight} 0%, ${colors.surfaceHover} 50%, ${colors.borderLight} 100%)`;

const shimmerStyle: React.CSSProperties = {
  background: shimmerBg,
  backgroundSize: "200% 100%",
  animation: "nousShimmer 1.5s ease-in-out infinite",
  borderRadius: radius.sm,
};


// Primitives


function Bar({ width, height = 12 }: { width: string | number; height?: number }) {
  return <div style={{ ...shimmerStyle, width, height, flexShrink: 0 }} />;
}


// Card skeleton


function Card() {
  return (
    <div style={{ ...card, marginBottom: space.md }}>
      {/* Header row: icon + title + status */}
      <div style={{ display: "flex", alignItems: "center", gap: space.md, marginBottom: space.sm }}>
        <div style={{ ...shimmerStyle, width: 32, height: 32, borderRadius: radius.md }} />
        <div style={{ flex: 1 }}>
          <Bar width="30%" height={10} />
          <div style={{ marginTop: 4 }}>
            <Bar width="60%" height={14} />
          </div>
        </div>
        <div style={{ ...shimmerStyle, width: 8, height: 8, borderRadius: "50%" }} />
      </div>
      {/* Detail grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(80px, 1fr))", gap: space.sm, marginTop: space.sm }}>
        <Bar width="100%" height={10} />
        <Bar width="100%" height={10} />
        <Bar width="100%" height={10} />
      </div>
    </div>
  );
}


// Grid skeleton


function Grid({ count = 6, cols = 3 }: { count?: number; cols?: number }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${cols}, 1fr)`,
        gap: space.lg,
        padding: space.xl,
      }}
    >
      {Array.from({ length: count }, (_, i) => (
        <Card key={i} />
      ))}
    </div>
  );
}


// Chat message skeleton


function Message({ isUser = false }: { isUser?: boolean }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: isUser ? "flex-end" : "flex-start",
        marginBottom: space.lg,
      }}
    >
      {/* Role label */}
      <div style={{ marginBottom: 4, width: 40 }}>
        <Bar width={40} height={10} />
      </div>
      {/* Content bubble */}
      <div
        style={{
          maxWidth: "75%",
          padding: `${space.md} ${space.lg}`,
          borderRadius: radius.lg,
          background: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <Bar width={isUser ? 120 : 280} height={14} />
        <div style={{ marginTop: 8 }}>
          <Bar width={isUser ? 80 : 220} height={14} />
        </div>
        {!isUser && (
          <div style={{ marginTop: 8 }}>
            <Bar width={160} height={14} />
          </div>
        )}
      </div>
    </div>
  );
}


// Page header skeleton


function PageHeader() {
  return (
    <div
      style={{
        padding: `${space.lg} ${space.xl}`,
        background: colors.surface,
        borderBottom: `1px solid ${colors.borderLight}`,
      }}
    >
      <Bar width={120} height={18} />
      <div style={{ marginTop: 4 }}>
        <Bar width={200} height={12} />
      </div>
    </div>
  );
}


// Export


export const Skeleton = { Card, Grid, Message, PageHeader };
