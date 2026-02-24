from django.db import models
from django.db.models import F
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

# this system here holdes the department information for each tools that is associated to the machine 
class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    location = models.CharField(max_length=100, blank=True) 

    def __str__(self):
        return self.name


class Machine(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="machines"
    )

    machine_name = models.CharField(max_length=100, unique=True)
    machine_type = models.CharField(max_length=100)
    machine_location = models.CharField(max_length=100)
    machine_status = models.CharField(max_length=100)
    machine_last_updated = models.DateTimeField(auto_now=True)
    machine_uptime = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.machine_name} ({self.department.name})"


class MachinePart(models.Model):
    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        related_name="parts"
    )

    model_number = models.CharField(max_length=100)
    part_name = models.CharField(max_length=100)
    part_description = models.TextField(blank=True)

    quantity_left = models.PositiveIntegerField(default=0)
    last_purchase_date = models.DateTimeField(null=True, blank=True)

    manufacturer_name = models.CharField(max_length=120, blank=True)
    manufacturer_phone = models.CharField(max_length=30, blank=True)

    vendor_name = models.CharField(max_length=120, blank=True)
    vendor_phone = models.CharField(max_length=30, blank=True)
    vendor_website = models.URLField(max_length=300, blank=True)

    class Meta:
        unique_together = ("machine", "model_number")

    def __str__(self):
        return f"{self.machine.machine_name} - {self.part_name} ({self.model_number})"
    

class MachineMaintenanceTrackRecord(models.Model):
    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        related_name="maintenance_records"
    )

    issue_description = models.TextField(blank=True)
    date_reported = models.DateTimeField(auto_now_add=True)
    date_fixed = models.DateTimeField(null=True, blank=True)
    time_to_fix = models.DurationField(null=True, blank=True)
    part_replaced = models.ForeignKey(
        MachinePart,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_records"
    )

    # mark whether this record has already consumed (subtracted) the part from inventory
    part_consumed = models.BooleanField(default=False)

    def __str__(self):
        return f"Maintenance for {self.machine.machine_name} reported {self.date_reported:%Y-%m-%d %H:%M}"


class User_Emails(models.Model):
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.email


