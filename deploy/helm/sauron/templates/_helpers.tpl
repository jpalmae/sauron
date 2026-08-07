{{- define "sauron.name" -}}sauron{{- end -}}
{{- define "sauron.image" -}}
{{- printf "%s%s:%s" (ternary (printf "%s/" .Values.image.registry) "" (ne .Values.image.registry "")) .repository .Values.image.tag -}}
{{- end -}}
