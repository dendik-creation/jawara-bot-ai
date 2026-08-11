"use client"

import * as React from "react"

import { DatasetList } from "@/components/dashboard/dataset-list"
import { FeedbackList } from "@/components/dashboard/feedback-list"
import { PageTitle } from "@/components/page/page-title"

export default function DatasetsPage() {
  const [datasetsRefreshKey, setDatasetsRefreshKey] = React.useState(0)

  return (
    <div className="flex flex-col gap-6">
      <PageTitle
        title="Datasets & Operator Feedback"
        description="Koreksi human-in-the-loop dari Threats, dikurasi menjadi dataset terversi dan tervalidasi."
      />

      <FeedbackList refreshKey={0} onAdded={() => setDatasetsRefreshKey((key) => key + 1)} />
      <DatasetList refreshKey={datasetsRefreshKey} />
    </div>
  )
}
