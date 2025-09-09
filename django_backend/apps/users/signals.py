from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in, user_logged_out

from .models import User, TeamMembership


@receiver(post_save, sender=User)
def user_post_save_handler(sender, instance, created, **kwargs):
    """
    Handle user creation and updates.
    """
    if created:
        # Set default preferences for new users
        if not instance.metadata:
            instance.metadata = {
                'onboarding_completed': False,
                'last_activity': None,
                'login_count': 0
            }
            instance.save(update_fields=['metadata'])


@receiver(user_logged_in)
def user_logged_in_handler(sender, request, user, **kwargs):
    """
    Handle user login events.
    """
    if hasattr(user, 'metadata') and user.metadata:
        metadata = user.metadata.copy()
        metadata['login_count'] = metadata.get('login_count', 0) + 1
        metadata['last_login_ip'] = request.META.get('REMOTE_ADDR')
        user.metadata = metadata
        user.save(update_fields=['metadata'])


@receiver(user_logged_out)
def user_logged_out_handler(sender, request, user, **kwargs):
    """
    Handle user logout events.
    """
    if user and hasattr(user, 'metadata') and user.metadata:
        metadata = user.metadata.copy()
        metadata['last_logout'] = str(user.last_login) if user.last_login else None
        user.metadata = metadata
        user.save(update_fields=['metadata'])


@receiver(post_save, sender=TeamMembership)
def team_membership_created_handler(sender, instance, created, **kwargs):
    """
    Handle team membership creation.
    """
    if created and instance.role == 'leader':
        # Update team lead if membership role is leader
        team = instance.team
        if team.lead != instance.user:
            team.lead = instance.user
            team.save(update_fields=['lead'])


@receiver(post_delete, sender=TeamMembership)
def team_membership_deleted_handler(sender, instance, **kwargs):
    """
    Handle team membership deletion.
    """
    team = instance.team

    # If the deleted membership was the team leader, clear the lead
    if team.lead == instance.user:
        # Try to assign leadership to another senior member
        new_leader_membership = team.memberships.filter(
            role__in=['leader', 'senior'],
            is_active=True
        ).exclude(user=instance.user).first()

        if new_leader_membership:
            team.lead = new_leader_membership.user
        else:
            team.lead = None

        team.save(update_fields=['lead'])
