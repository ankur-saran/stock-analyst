{{- define "stock-analyst-obs.labels" -}}
app.kubernetes.io/part-of: stock-analyst
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}
