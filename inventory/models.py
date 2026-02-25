from django.db import models


# ==============================
# LOCATION STRUCTURE
# ==============================

class Building(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)

    building = models.ForeignKey(
        Building,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="departments"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ==============================
# MACHINE STRUCTURE
# ==============================

class Machine(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="machines"
    )

    machine_name = models.CharField(max_length=100, unique=True)
    machine_type = models.CharField(max_length=100)
    machine_location = models.CharField(max_length=100)

    machine_image = models.ImageField(
        upload_to="machine_images/",
        blank=True,
        null=True
    )

    class Meta:
        ordering = ["machine_name"]

    def __str__(self):
        return f"{self.machine_name} ({self.department.name})"


# ==============================
# PART STRUCTURE
# ==============================

class Part(models.Model):
    model_number = models.CharField(
        max_length=100,
        db_index=True  # Optimized search
    )

    part_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    part_image = models.ImageField(
        upload_to="part_images/",
        blank=True,
        null=True
    )

    usage_description = models.TextField(
        blank=True,
        help_text="What this part is used for"
    )

    class Meta:
        ordering = ["model_number"]

    def __str__(self):
        return f"{self.part_name} ({self.model_number})"


# ==============================
# MACHINE INVENTORY (Bridge)
# ==============================

class MachinePart(models.Model):
    machine = models.ForeignKey(
        Machine,
        on_delete=models.CASCADE,
        related_name="machine_parts"
    )

    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name="machine_parts"
    )

    quantity_left = models.PositiveIntegerField(
        default=0,
        db_index=True  # Fast low-stock filtering
    )

    placement_location = models.CharField(
        max_length=200,
        blank=True,
        help_text="Where the part is installed in the machine"
    )

    compatibility_notes = models.TextField(blank=True)

    class Meta:
        unique_together = ("machine", "part")
        ordering = ["machine"]

    def __str__(self):
        return f"{self.machine.machine_name} - {self.part.part_name}"


# ==============================
# MAINTENANCE TRACKING
# ==============================

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
        Part,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="maintenance_records"
    )

    part_consumed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date_reported"]

    def __str__(self):
        return f"Maintenance for {self.machine.machine_name} on {self.date_reported:%Y-%m-%d}"


# ==============================
# VENDOR STRUCTURE
# ==============================

class Vendor(models.Model):
    name = models.CharField(max_length=120, unique=True)
    phone = models.CharField(max_length=30, blank=True)
    website = models.URLField(max_length=300, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Manufacturer(models.Model):
    name = models.CharField(max_length=120, unique=True)
    phone = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# ==============================
# VENDOR ↔ PART RELATIONSHIP
# ==============================

class VendorPart(models.Model):
    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name="vendor_links"
    )

    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.CASCADE,
        related_name="part_links"
    )

    manufacturer = models.ForeignKey(
        Manufacturer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    last_purchase_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("part", "vendor")
        ordering = ["part"]

    def __str__(self):
        return f"{self.part.model_number} supplied by {self.vendor.name}"


# ==============================
# USER REQUIREMENTS
# ==============================

class UserRequirement(models.Model):
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="user_requirements"
    )

    requirement_description = models.TextField(blank=True)
    name_of_requester = models.CharField(max_length=100, blank=True)
    date_reported = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_reported"]

    def __str__(self):
        return f"Requirement from {self.department.name}"
    

class UserEmail(models.Model):
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.email
    