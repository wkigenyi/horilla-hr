from django.contrib import admin

from ohs import models as ohs_models

admin.site.register(ohs_models.OshWorkplace)
admin.site.register(ohs_models.OshEvent)
admin.site.register(ohs_models.OshNotification)
admin.site.register(ohs_models.OshInvestigation)
admin.site.register(ohs_models.OshCorrectiveAction)
admin.site.register(ohs_models.OshPolicy)
admin.site.register(ohs_models.OshPolicyAcknowledgement)
admin.site.register(ohs_models.OshSafetyCommittee)
admin.site.register(ohs_models.OshCommitteeMeeting)
admin.site.register(ohs_models.OshMedicalRecord)
admin.site.register(ohs_models.OshPpeAssignment)
admin.site.register(ohs_models.OshTrainingRecord)
