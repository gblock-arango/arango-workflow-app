"use client";

import AppHeader from "@/components/layout/AppHeader";
import PageContent from "@/components/layout/PageContent";

export default function AdaptiveCdcPage() {
  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <AppHeader
        title="Adaptive CDC"
        subtitle="Stream-aligned graph sync and change-data capture workflows"
      />
      <PageContent className="py-10">
        <div className="w-full bg-white rounded-xl border border-gray-200 p-8 shadow-sm">
          <p className="text-gray-600">
            Adaptive CDC configuration and monitoring will live here. Connect
            lakehouse tables to your graph and track stream sync status from the
            home page medallion row.
          </p>
        </div>
      </PageContent>
    </main>
  );
}
